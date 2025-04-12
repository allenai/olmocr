
import os
import wandb
import logging
import torch
import torch.distributed

from pathlib import Path
from logging import Logger
from typing import Optional
from tempfile import TemporaryDirectory


from datasets.utils import disable_progress_bars
from datasets.utils.logging import set_verbosity
from peft import LoraConfig, get_peft_model  # pyright: ignore
from transformers import (
    AutoProcessor,
    Qwen2VLForConditionalGeneration,
    Trainer,
    TrainerCallback,
    TrainingArguments,
)
from transformers.integrations import WandbCallback
from transformers.trainer_callback import TrainerControl, TrainerState
from transformers.trainer_utils import get_last_checkpoint

from olmocr.train.core.cli import make_cli, save_config, to_native_types
from olmocr.train.core.config import TrainConfig
from olmocr.train.core.loggers import get_logger
from olmocr.train.core.paths import copy_dir, join_path
from olmocr.train.core.state import BeakerState

from .utils import (
    RunName,
    TruncatingCollator,
    get_local_dir,
    log_trainable_parameters,
    make_dataset,
    setup_environment,
)


class CheckpointUploadCallback(TrainerCallback):
    def __init__(self, save_path: str, logger: Optional[Logger] = None):
        self.save_path = save_path
        self.logger = logger or get_logger(self.__class__.__name__)

    def on_save(self, args: TrainingArguments, state: TrainerState, control: TrainerControl, **kwargs):
        if state.is_local_process_zero:
            latest_checkpoint = get_last_checkpoint(args.output_dir)
            if not latest_checkpoint:
                return

            dir_name = Path(latest_checkpoint).name
            copy_dir(str(latest_checkpoint), f"{self.save_path}/{dir_name}")
            self.logger.info("Saved checkpoint to %s", f"{self.save_path}/{dir_name}")


def update_wandb_config(config: TrainConfig, trainer: Trainer, model: torch.nn.Module):
    # finding wandb callback
    callbacks = [c for c in trainer.callback_handler.callbacks if isinstance(c, WandbCallback)]  # pyright: ignore
    if not callbacks:
        raise ValueError("WandbCallback not found in trainer callbacks")

    wandb_callback = callbacks[0]
    peft_config = to_native_types(getattr(model, "peft_config", {}))
    script_config = to_native_types(config)
    beaker_envs = {k: v for k, v in os.environ.items() if k.lower().startswith("beaker")}

    on_setup_fn = wandb_callback.setup

    def setup_and_update(args, state, model, **kwargs):
        on_setup_fn(args=args, state=state, model=model, **kwargs)
        wandb.config.update({"peft": peft_config}, allow_val_change=True)
        wandb.config.update({"script": script_config}, allow_val_change=True)
        wandb.config.update({"beaker": beaker_envs}, allow_val_change=True)
        if (run := wandb.run) and (beaker_url := BeakerState().url):
            run.notes = beaker_url

    wandb_callback.setup = setup_and_update


def get_rank() -> int:
    if torch.distributed.is_available() and torch.distributed.is_initialized():
        return torch.distributed.get_rank()
    return 0


def run_train(config: TrainConfig):
    if get_rank() == 0:
        logger_level = logging.INFO
    else:
        logger_level = logging.WARN
        disable_progress_bars()

    logger = get_logger(__name__, level=logger_level)
    set_verbosity(logger_level)

    run_name = RunName.get(config)

    setup_environment(aws_config=config.aws, wandb_config=config.wandb, WANDB_RUN_GROUP=run_name.group)

    processor = AutoProcessor.from_pretrained(config.model.name_or_path, trust_remote_code=True)
    train_dataset, valid_dataset = make_dataset(config, processor)
    logger.info(train_dataset)
    logger.info(valid_dataset)

    if "qwen" in config.model.name_or_path.lower():
        model = Qwen2VLForConditionalGeneration.from_pretrained(
            config.model.name_or_path, torch_dtype=torch.bfloat16, _attn_implementation="flash_attention_2" if config.model.use_flash_attn else None
        )
    else:
        from .molmo.config_molmo import MolmoConfig
        from .molmo.modeling_molmo import MolmoForCausalLM

        model_config = MolmoConfig.from_pretrained(config.model.name_or_path, trust_remote_code=True)

        if model_config.max_position_embeddings < config.generate.max_length:
            logger.warning(
                f"ALERT, force adjusting model config max_position_embeddings upwards from {model_config.max_position_embeddings} to {config.generate.max_length}"
            )
            model_config.max_position_embeddings = config.generate.max_length

        if config.model.use_flash_attn:
            model_config.attention_type = "flash"

        model = MolmoForCausalLM.from_pretrained(config.model.name_or_path, torch_dtype=torch.bfloat16, config=model_config, trust_remote_code=True)

    logger.info(model)

    if config.lora is not None:
        peft_config = LoraConfig(
            r=config.lora.rank,
            lora_alpha=config.lora.alpha,
            lora_dropout=config.lora.dropout,
            bias=config.lora.bias,  # pyright: ignore
            task_type=config.lora.task_type,
            target_modules=list(config.lora.target_modules),
        )
        model = get_peft_model(model=model, peft_config=peft_config)
        log_trainable_parameters(model=model, logger=logger)

    save_path = join_path("", config.save.path, run_name.run)

    # Make sure directory exists if local
    if not save_path.startswith("s3://"):
        os.makedirs(os.path.dirname(save_path), exist_ok=True)

    save_config(config, join_path("", save_path, "config.yaml"))  # pyright: ignore

    with TemporaryDirectory() as output_dir:
        training_args = TrainingArguments(
            run_name=run_name.run,
            logging_steps=config.hparams.log_every_steps,
            output_dir=output_dir,
            eval_strategy="steps",
            report_to="wandb",
            # report_to=[],  # disable logging to wandb, we will use a custom callback
            optim=config.hparams.optim,
            eval_steps=config.hparams.eval_every_steps,
            learning_rate=config.hparams.learning_rate,
            per_device_train_batch_size=config.hparams.batch_size,
            per_device_eval_batch_size=config.hparams.eval_batch_size or config.hparams.batch_size,
            gradient_checkpointing=config.hparams.gradient_checkpointing,
            gradient_checkpointing_kwargs=(
                dict(use_reentrant=False)  # from this issue: https://github.com/huggingface/peft/issues/1142
                if config.hparams.gradient_checkpointing and config.lora is not None
                else {}
            ),
            gradient_accumulation_steps=config.hparams.gradient_accumulation_steps,
            max_steps=config.hparams.max_steps,
            weight_decay=config.hparams.weight_decay,
            dataloader_num_workers=config.max_workers,
            load_best_model_at_end=True,
            save_strategy="steps",
            ddp_find_unused_parameters=config.hparams.find_unused_parameters,
            save_steps=config.save.save_every_steps,
            warmup_steps=config.hparams.warmup_steps,
            warmup_ratio=config.hparams.warmup_ratio,
            bf16=True,
            label_names=["labels"],  # fix from https://github.com/huggingface/transformers/issues/22885
            max_grad_norm=config.hparams.clip_grad_norm,
            remove_unused_columns=False,
            eval_on_start=True,
            metric_for_best_model=config.valid_data.metric_for_best_model,
        )

        data_collator = TruncatingCollator(max_length=config.generate.max_length)

        checkpoint_callback = CheckpointUploadCallback(save_path=save_path, logger=logger)

        # Initialize Trainer
        trainer = Trainer(
            model=model,
            args=training_args,
            train_dataset=train_dataset,
            eval_dataset=valid_dataset,
            tokenizer=processor.tokenizer,
            data_collator=data_collator,
            callbacks=[checkpoint_callback],
        )

        # Train the model
        trainer.train()  # pyright: ignore

        if get_rank() == 0:
            with get_local_dir(join_path("", save_path, "best")) as best_dir:
                if config.lora is not None:
                    logger.info("Merging LoRA adapters into the base model...")
                    model = model.merge_and_unload()
                    logger.info("LoRA adapters merged successfully.")

                model.save_pretrained(best_dir)

                logger.info("Saved best model to %s", best_dir)

        # Uncomment to test speed of data loader
        # train_dataloader = DataLoader(formatted_dataset["train"], batch_size=1, num_workers=4, shuffle=False)
        # for entry in tqdm(train_dataloader):
        #     print("Step!")
        #     model.forward(**{k: v.to("cuda:0") for (k,v) in entry.items()})


def main():
    train_config = make_cli(TrainConfig)  # pyright: ignore
    run_train(train_config)


if __name__ == "__main__":
    main()
