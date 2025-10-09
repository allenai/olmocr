"""
Simple script to test OlmOCR dataset loading with YAML configuration.
"""

import argparse
import logging
import math
import os
import shutil
from typing import Any, Dict, Optional

import numpy as np
import torch
import wandb
from torch.amp import autocast
from torch.optim import AdamW
from torch.utils.data import ConcatDataset, DataLoader
from tqdm import tqdm
from transformers import (
    AutoProcessor,
    Qwen2_5_VLForConditionalGeneration,
    Qwen2VLForConditionalGeneration,
    Qwen3VLMoeForConditionalGeneration,
    get_scheduler,
)

from olmocr.train.config import Config
from olmocr.train.dataloader import BaseMarkdownPDFDataset
from olmocr.train.muon import SingleDeviceMuonWithAuxAdam

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    datefmt="%m/%d/%Y %H:%M:%S",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


class QwenDataCollator:
    """Data collator for vision-language models that handles numpy arrays."""

    def __init__(self, max_token_len: Optional[int] = None):
        self.max_token_len = max_token_len

    def __call__(self, examples):
        # Filter out None values and extract the fields we need
        batch = {"input_ids": [], "attention_mask": [], "labels": [], "pixel_values": [], "image_grid_thw": []}

        for example in examples:
            if example is not None:
                # Convert numpy arrays to tensors
                input_ids = torch.from_numpy(example["input_ids"]) if isinstance(example["input_ids"], np.ndarray) else example["input_ids"]
                attention_mask = torch.from_numpy(example["attention_mask"]) if isinstance(example["attention_mask"], np.ndarray) else example["attention_mask"]
                labels = torch.from_numpy(example["labels"]) if isinstance(example["labels"], np.ndarray) else example["labels"]

                # Trim to max_token_len if specified
                if self.max_token_len is not None:
                    input_ids = input_ids[: self.max_token_len]
                    attention_mask = attention_mask[: self.max_token_len]
                    labels = labels[: self.max_token_len]

                batch["input_ids"].append(input_ids)
                batch["attention_mask"].append(attention_mask)
                batch["labels"].append(labels)

                # Handle pixel_values which might be numpy array or already a tensor
                pixel_values = example["pixel_values"]
                if isinstance(pixel_values, np.ndarray):
                    pixel_values = torch.from_numpy(pixel_values)
                batch["pixel_values"].append(pixel_values)

                # Handle image_grid_thw
                image_grid_thw = example["image_grid_thw"]
                if isinstance(image_grid_thw, np.ndarray):
                    image_grid_thw = torch.from_numpy(image_grid_thw)
                batch["image_grid_thw"].append(image_grid_thw)

        # Check if we have any valid samples
        if not batch["input_ids"]:
            return None

        # Convert lists to tensors with proper padding
        # Note: For Qwen2-VL, we typically handle variable length sequences
        # The model's processor should handle the padding internally
        return {
            "input_ids": torch.stack(batch["input_ids"]),
            "attention_mask": torch.stack(batch["attention_mask"]),
            "labels": torch.stack(batch["labels"]),
            "pixel_values": torch.stack(batch["pixel_values"]),  # Stack into tensor
            "image_grid_thw": torch.stack(batch["image_grid_thw"]),
        }


def save_checkpoint(
    model: torch.nn.Module,
    optimizer: torch.optim.Optimizer,
    lr_scheduler: Any,
    epoch: float,
    global_step: int,
    samples_seen: int,
    best_metric: float,
    output_dir: str,
    save_total_limit: Optional[int] = None,
):
    """Save model, optimizer, scheduler, and training state."""
    checkpoint_dir = os.path.join(output_dir, f"checkpoint-{global_step}")
    os.makedirs(checkpoint_dir, exist_ok=True)

    # Save model
    model.save_pretrained(checkpoint_dir)

    # Save optimizer and scheduler
    torch.save(optimizer.state_dict(), os.path.join(checkpoint_dir, "optimizer.pt"))
    torch.save(lr_scheduler.state_dict(), os.path.join(checkpoint_dir, "scheduler.pt"))

    # Save training state
    state = {
        "epoch": epoch,
        "global_step": global_step,
        "samples_seen": samples_seen,
        "best_metric": best_metric,
    }
    torch.save(state, os.path.join(checkpoint_dir, "training_state.pt"))

    logger.info(f"Saved checkpoint to {checkpoint_dir}")

    # Enforce save_total_limit by removing oldest checkpoints
    if save_total_limit is not None and save_total_limit > 0:
        checkpoints = sorted([d for d in os.listdir(output_dir) if d.startswith("checkpoint-")], key=lambda x: int(x.split("-")[1]))
        while len(checkpoints) > save_total_limit:
            oldest = checkpoints.pop(0)
            shutil.rmtree(os.path.join(output_dir, oldest))
            logger.info(f"Deleted old checkpoint: {oldest}")


def load_checkpoint(
    model_class: type,
    init_kwargs: Dict[str, Any],
    optimizer: torch.optim.Optimizer,
    lr_scheduler: Any,
    checkpoint_dir: str,
    device: torch.device,
) -> tuple[torch.nn.Module, Dict[str, Any]]:
    """Load model, optimizer, scheduler, and training state from checkpoint."""
    model = model_class.from_pretrained(checkpoint_dir, **init_kwargs)
    model.to(device)

    optimizer.load_state_dict(torch.load(os.path.join(checkpoint_dir, "optimizer.pt"), map_location=device))
    lr_scheduler.load_state_dict(torch.load(os.path.join(checkpoint_dir, "scheduler.pt"), map_location=device))

    state = torch.load(os.path.join(checkpoint_dir, "training_state.pt"), map_location=device)
    logger.info(f"Resumed from checkpoint: {checkpoint_dir} at epoch {state['epoch']:.2f}, step {state['global_step']}, samples seen {state['samples_seen']}")
    return model, state


def evaluate_model(
    model: torch.nn.Module,
    eval_dataloaders: Dict[str, DataLoader],
    device: torch.device,
) -> Dict[str, float]:
    """Evaluate on all eval datasets and return average loss per dataset."""
    model.eval()
    eval_metrics = {}

    for dataset_name, dataloader in eval_dataloaders.items():
        total_loss = 0.0
        num_batches = 0

        with torch.no_grad():
            for batch in dataloader:
                # Skip if batch is None (all samples were filtered out)
                if batch is None:
                    continue
                batch = {k: v.to(device) for k, v in batch.items()}
                with autocast(device_type="cuda", enabled=True, dtype=torch.bfloat16):
                    outputs = model(**batch)
                total_loss += outputs.loss.item()
                num_batches += 1

        avg_loss = total_loss / num_batches if num_batches > 0 else 0.0
        eval_metrics[f"eval_{dataset_name}_loss"] = avg_loss
        logger.info(f"Eval {dataset_name} loss: {avg_loss:.4f}")

    # Compute overall eval loss as average across datasets (or customize as needed)
    if eval_metrics:
        overall_loss = sum(eval_metrics.values()) / len(eval_metrics)
        eval_metrics["eval_loss"] = overall_loss

    return eval_metrics


def create_train_dataloader(
    train_dataset,
    config,
    data_collator,
    seed_worker,
    epoch_num: int = 0,
) -> DataLoader:
    """Create a training dataloader with epoch-specific shuffling.

    Args:
        train_dataset: The training dataset
        config: Training configuration
        data_collator: Data collator for batching
        seed_worker: Worker initialization function
        epoch_num: Current epoch number for seed generation

    Returns:
        DataLoader with epoch-specific shuffling
    """
    # Create generator with epoch-specific seed for different shuffling each epoch
    epoch_generator = torch.Generator()
    if config.training.data_seed is not None:
        # Use epoch number to ensure different shuffling each epoch while maintaining reproducibility
        epoch_generator.manual_seed(config.training.data_seed + epoch_num)
    else:
        # Use a random seed if no data_seed specified
        epoch_generator.manual_seed(int(torch.randint(0, 2**32 - 1, (1,)).item()))

    return DataLoader(
        train_dataset,
        batch_size=config.training.per_device_train_batch_size,
        shuffle=True,
        collate_fn=data_collator,
        num_workers=config.training.dataloader_num_workers,
        drop_last=config.training.dataloader_drop_last,
        worker_init_fn=seed_worker,
        generator=epoch_generator,
    )


def main():
    parser = argparse.ArgumentParser(description="Train OlmOCR model")
    parser.add_argument("--config", type=str, default="olmocr/train/configs/example_config.yaml", help="Path to YAML configuration file")

    args = parser.parse_args()

    # Load configuration
    logger.info(f"Loading configuration from: {args.config}")
    config = Config.from_yaml(args.config)

    # Validate configuration
    try:
        config.validate()
    except ValueError as e:
        logger.error(f"Configuration validation failed: {e}")
        return

    # Set wandb project from config
    if config.project_name:
        os.environ["WANDB_PROJECT"] = config.project_name
        logger.info(f"Setting WANDB_PROJECT to: {config.project_name}")

    # Initialize wandb if reporting to it
    if "wandb" in config.training.report_to:
        wandb.init(project=config.project_name, name=config.run_name, config=config.to_dict())

    # Load processor for tokenization
    logger.info(f"Loading processor: {config.model.name}")
    processor = AutoProcessor.from_pretrained(
        config.model.name,
    )

    # Model init kwargs to reuse for loading checkpoints
    model_init_kwargs = {
        "torch_dtype": getattr(torch, config.model.torch_dtype) if config.model.torch_dtype != "auto" else "auto",
        "device_map": config.model.device_map,
        "trust_remote_code": config.model.trust_remote_code,
        "attn_implementation": config.model.attn_implementation if config.model.use_flash_attention else None,
    }

    # Load model
    logger.info(f"Loading model: {config.model.name}")
    if "qwen2.5-vl" in config.model.name.lower():
        model_class = Qwen2_5_VLForConditionalGeneration
    elif "qwen2-vl" in config.model.name.lower():
        model_class = Qwen2VLForConditionalGeneration
    elif "qwen3-vl" in config.mode.name.lower():
        model_class = Qwen3VLMoeForConditionalGeneration
    else:
        raise NotImplementedError()

    model = model_class.from_pretrained(config.model.name, **model_init_kwargs)

    # Enable gradient checkpointing if configured
    if config.training.gradient_checkpointing:
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs=config.training.gradient_checkpointing_kwargs)

    # Create training datasets
    logger.info("Creating training datasets...")
    train_datasets = []
    for i, dataset_cfg in enumerate(config.dataset.train):
        root_dir = dataset_cfg["root_dir"]
        pipeline_steps = config.get_pipeline_steps(dataset_cfg["pipeline"], processor)

        logger.info(f"Creating training dataset {i+1} from: {root_dir}")
        dataset = BaseMarkdownPDFDataset(root_dir, pipeline_steps)
        logger.info(f"Found {len(dataset)} samples")

        if len(dataset) > 0:
            train_datasets.append(dataset)

    # Combine all training datasets
    train_dataset = ConcatDataset(train_datasets) if len(train_datasets) > 1 else train_datasets[0]
    logger.info(f"Total training samples: {len(train_dataset)}")

    # Create evaluation datasets
    logger.info("Creating evaluation datasets...")
    eval_datasets = {}
    for i, dataset_cfg in enumerate(config.dataset.eval):
        root_dir = dataset_cfg["root_dir"]
        pipeline_steps = config.get_pipeline_steps(dataset_cfg["pipeline"], processor)

        # Use dataset name if provided, otherwise use root_dir as name
        dataset_name = dataset_cfg.get("name", f"eval_dataset_{i+1}")

        logger.info(f"Creating evaluation dataset '{dataset_name}' from: {root_dir}")
        dataset = BaseMarkdownPDFDataset(root_dir, pipeline_steps)
        logger.info(f"Found {len(dataset)} samples")

        if len(dataset) > 0:
            eval_datasets[dataset_name] = dataset

    # Log total evaluation samples across all datasets
    total_eval_samples = sum(len(dataset) for dataset in eval_datasets.values())
    logger.info(f"Total evaluation samples across {len(eval_datasets)} datasets: {total_eval_samples}")

    # Construct full output directory by appending run_name to base output_dir
    full_output_dir = os.path.join(config.training.output_dir, config.run_name)
    logger.info(f"Setting output directory to: {full_output_dir}")
    os.makedirs(full_output_dir, exist_ok=True)

    # Check for existing checkpoints if any
    found_resumable_checkpoint = None
    if os.path.exists(full_output_dir):
        # Look for checkpoint directories
        checkpoint_dirs = [d for d in os.listdir(full_output_dir) if d.startswith("checkpoint-") and os.path.isdir(os.path.join(full_output_dir, d))]
        if checkpoint_dirs:
            # Sort by checkpoint number and get the latest
            checkpoint_dirs.sort(key=lambda x: int(x.split("-")[1]))
            latest_checkpoint = os.path.join(full_output_dir, checkpoint_dirs[-1])
            logger.info(f"Found existing checkpoint: {latest_checkpoint}")
            found_resumable_checkpoint = latest_checkpoint
        else:
            logger.info("No existing checkpoints found in output directory")

    # Set seeds
    torch.manual_seed(config.training.seed)

    # Set up data loader seed worker function
    def seed_worker(worker_id):
        worker_seed = torch.initial_seed() % 2**32
        np.random.seed(worker_seed)
        import random

        random.seed(worker_seed)

    # Device setup
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)

    # Apply torch compile if enabled
    if config.training.torch_compile:
        logger.info(f"Compiling model with torch.compile (backend={config.training.torch_compile_backend}, mode={config.training.torch_compile_mode})")
        model = torch.compile(
            model,
            backend=config.training.torch_compile_backend,
            mode=config.training.torch_compile_mode,
            fullgraph=config.training.torch_compile_fullgraph,
            dynamic=config.training.torch_compile_dynamic,
        )
        logger.info("Model compilation complete")

    # Set up optimizer
    if config.training.optim == "adamw_torch":
        no_decay = ["bias", "LayerNorm.weight"]
        optimizer_grouped_parameters = [
            {
                "params": [p for n, p in model.named_parameters() if not any(nd in n for nd in no_decay)],
                "weight_decay": config.training.weight_decay,
            },
            {
                "params": [p for n, p in model.named_parameters() if any(nd in n for nd in no_decay)],
                "weight_decay": 0.0,
            },
        ]
        optimizer = AdamW(
            optimizer_grouped_parameters,
            lr=float(config.training.learning_rate),
            betas=(config.training.adam_beta1, config.training.adam_beta2),
            eps=float(config.training.adam_epsilon),
        )
    elif config.training.optim == "muon":
        # Separate parameters for Muon (hidden matrices) and Adam (embeddings, scalars, head)
        hidden_matrix_params = [p for n, p in model.named_parameters() if p.ndim >= 2 and "embed" not in n and "lm_head" not in n]
        embed_params = [p for n, p in model.named_parameters() if "embed" in n]
        scalar_params = [p for p in model.parameters() if p.ndim < 2]
        head_params = [p for n, p in model.named_parameters() if "lm_head" in n]

        # Create Adam groups with different learning rates
        adam_groups = [
            dict(params=head_params, lr=float(config.training.learning_rate) * config.training.muon_lr_multiplier_head, use_muon=False),
            dict(params=embed_params, lr=float(config.training.learning_rate) * config.training.muon_lr_multiplier_embed, use_muon=False),
            dict(params=scalar_params, lr=float(config.training.learning_rate) * config.training.muon_lr_multiplier_scalar, use_muon=False),
        ]

        # Add Adam hyperparameters to groups
        for g in adam_groups:
            g["betas"] = (config.training.adam_beta1, config.training.adam_beta2)
            g["eps"] = float(config.training.adam_epsilon)
            g["weight_decay"] = config.training.weight_decay

        # Create Muon group
        muon_group = dict(
            params=hidden_matrix_params,
            lr=float(config.training.learning_rate),
            momentum=config.training.muon_momentum,
            weight_decay=config.training.weight_decay,
            use_muon=True,
        )

        # Combine all groups
        param_groups = [*adam_groups, muon_group]
        optimizer = SingleDeviceMuonWithAuxAdam(param_groups)
    else:
        raise NotImplementedError(f"Optimizer {config.training.optim} not supported in custom loop")

    # Total training steps calculation
    samples_per_step = config.training.per_device_train_batch_size * config.training.gradient_accumulation_steps
    num_update_steps_per_epoch = math.ceil(len(train_dataset) / samples_per_step)
    max_train_steps = int(math.ceil(config.training.num_train_epochs * num_update_steps_per_epoch))
    max_train_samples = int(math.ceil(config.training.num_train_epochs * len(train_dataset)))

    # Set up scheduler
    lr_scheduler = get_scheduler(
        name=config.training.lr_scheduler_type,
        optimizer=optimizer,
        num_warmup_steps=int(max_train_steps * config.training.warmup_ratio),
        num_training_steps=max_train_steps,
        scheduler_specific_kwargs=config.training.lr_scheduler_kwargs,
    )

    # Data collator
    data_collator = QwenDataCollator(max_token_len=config.training.collator_max_token_len)

    # Resume from checkpoint if available
    global_step = 0
    samples_seen = 0
    best_metric = float("inf") if not config.training.greater_is_better else -float("inf")

    if found_resumable_checkpoint:
        model, state = load_checkpoint(model_class, model_init_kwargs, optimizer, lr_scheduler, found_resumable_checkpoint, device)
        global_step = state["global_step"]
        best_metric = state["best_metric"]
        samples_seen = state["samples_seen"]

    # Create dataloaders - use epoch 0 initially (will be recreated with proper epoch if resuming)
    current_epoch_num = int(samples_seen / len(train_dataset)) if samples_seen > 0 else 0
    train_dataloader = create_train_dataloader(
        train_dataset,
        config,
        data_collator,
        seed_worker,
        epoch_num=current_epoch_num,
    )

    eval_dataloaders = {
        name: DataLoader(
            dataset,
            batch_size=config.training.per_device_eval_batch_size,
            shuffle=False,
            collate_fn=data_collator,
            num_workers=config.training.dataloader_num_workers,
            drop_last=False,
        )
        for name, dataset in eval_datasets.items()
    }

    # Always evaluate on start
    metrics = evaluate_model(model, eval_dataloaders, device)
    logger.info(f"Initial evaluation: {metrics}")
    if "wandb" in config.training.report_to:
        wandb.log(metrics, step=global_step)

    # Main training loop
    current_epoch = samples_seen / len(train_dataset)
    logger.info(f"Starting training from epoch {current_epoch:.2f} (step {global_step}, samples {samples_seen}) to {config.training.num_train_epochs} epochs")
    logger.info(f"Total training steps: {max_train_steps}, Total samples to process: {max_train_samples}")

    if samples_seen >= max_train_samples:
        logger.info("Training already completed based on samples seen!")
        logger.info("Skipping to final model save.")
    else:
        model.train()
        accumulated_loss = 0.0
        num_losses_accumulated = 0

        # Create epoch iterator and skip samples if resuming
        epoch_iterator = iter(train_dataloader)
        if samples_seen > 0:
            samples_to_skip = samples_seen % len(train_dataset)
            batches_to_skip = samples_to_skip // config.training.per_device_train_batch_size
            logger.info(f"Resuming training: skipping {batches_to_skip} batches ({samples_to_skip} samples) to reach position {samples_seen}")

            # Skip batches to resume from the correct position within the epoch
            for _ in range(batches_to_skip):
                try:
                    next(epoch_iterator)
                except StopIteration:
                    # We've reached the end of the epoch while skipping
                    # This shouldn't normally happen, but handle it gracefully
                    logger.warning(f"Reached end of epoch while skipping batches. Creating new epoch.")
                    current_epoch_num += 1
                    train_dataloader = create_train_dataloader(
                        train_dataset,
                        config,
                        data_collator,
                        seed_worker,
                        epoch_num=current_epoch_num,
                    )
                    epoch_iterator = iter(train_dataloader)
                    break

        # Create progress bar
        pbar = tqdm(total=max_train_samples - samples_seen, desc=f"Training from step {global_step}", unit="samples")

        while samples_seen < max_train_samples and global_step < max_train_steps:
            try:
                batch = next(epoch_iterator)
            except StopIteration:
                # End of epoch, create new dataloader with fresh shuffle
                current_epoch = samples_seen / len(train_dataset)
                logger.info(f"Completed epoch {current_epoch:.2f}")

                # Increment epoch number for new shuffle seed
                current_epoch_num += 1

                # Recreate dataloader with new generator for fresh shuffle
                train_dataloader = create_train_dataloader(
                    train_dataset,
                    config,
                    data_collator,
                    seed_worker,
                    epoch_num=current_epoch_num,
                )
                epoch_iterator = iter(train_dataloader)
                batch = next(epoch_iterator)

            # Skip if batch is None (all samples were filtered out)
            if batch is None:
                continue

            batch = {k: v.to(device) for k, v in batch.items()}

            with autocast(device_type="cuda", enabled=True, dtype=torch.bfloat16):
                outputs = model(**batch)
            loss = outputs.loss / config.training.gradient_accumulation_steps
            loss.backward()

            accumulated_loss += outputs.loss.item()  # Use undivided loss for logging
            num_losses_accumulated += 1
            samples_seen += config.training.per_device_train_batch_size

            # Update progress bar
            pbar.update(config.training.per_device_train_batch_size)

            # Check if we should do a gradient update
            if samples_seen % samples_per_step == 0 or samples_seen >= max_train_samples:
                # Clip gradients
                torch.nn.utils.clip_grad_norm_(model.parameters(), config.training.max_grad_norm)

                # Step optimizer and scheduler
                optimizer.step()
                lr_scheduler.step()
                optimizer.zero_grad()

                global_step += 1
                current_epoch = samples_seen / len(train_dataset)

                # Update progress bar with current stats
                current_lr = lr_scheduler.get_last_lr()[0]
                avg_loss = accumulated_loss / num_losses_accumulated if num_losses_accumulated > 0 else 0
                pbar.set_postfix({"loss": f"{avg_loss:.4f}", "lr": f"{current_lr:.2e}", "epoch": f"{current_epoch:.2f}", "step": global_step})

                # Logging
                if config.training.logging_steps > 0 and global_step % config.training.logging_steps == 0:
                    avg_train_loss = accumulated_loss / num_losses_accumulated if num_losses_accumulated > 0 else 0
                    logs = {
                        "train_loss": avg_train_loss,
                        "learning_rate": lr_scheduler.get_last_lr()[0],
                        "epoch": current_epoch,
                        "samples_seen": samples_seen,
                    }
                    logger.info(f"Step {global_step}: epoch={current_epoch:.3f}, loss={avg_train_loss:.4f}, lr={lr_scheduler.get_last_lr()[0]:.2e}")
                    if "wandb" in config.training.report_to:
                        wandb.log(logs, step=global_step)

                    accumulated_loss = 0.0
                    num_losses_accumulated = 0

                # Evaluation
                if config.training.eval_steps > 0 and global_step % config.training.eval_steps == 0 and global_step > 0:
                    metrics = evaluate_model(model, eval_dataloaders, device)
                    logger.info(f"Evaluation at step {global_step}: {metrics}")
                    if "wandb" in config.training.report_to:
                        wandb.log(metrics, step=global_step)

                    # Update best metric
                    current_metric = metrics.get(config.training.metric_for_best_model, None)
                    if current_metric is not None:
                        if (config.training.greater_is_better and current_metric > best_metric) or (
                            not config.training.greater_is_better and current_metric < best_metric
                        ):
                            best_metric = current_metric

                    # Return to training mode
                    model.train()

                # Saving
                if config.training.save_steps > 0 and global_step % config.training.save_steps == 0:
                    save_checkpoint(
                        model, optimizer, lr_scheduler, current_epoch, global_step, samples_seen, best_metric, full_output_dir, config.training.save_total_limit
                    )

            # Check if we've reached our training limit
            if samples_seen >= max_train_samples or global_step >= max_train_steps:
                break

        # Close progress bar
        pbar.close()

    # Save the final checkpoint with step number
    logger.info(f"Saving final checkpoint at step {global_step}...")
    save_checkpoint(model, optimizer, lr_scheduler, current_epoch, global_step, samples_seen, best_metric, full_output_dir, config.training.save_total_limit)

    # Log final training state
    final_epoch = samples_seen / len(train_dataset)
    logger.info(f"Training completed at epoch {final_epoch:.3f}, step {global_step}, samples {samples_seen}")

    # Final evaluation
    final_metrics = evaluate_model(model, eval_dataloaders, device)
    logger.info(f"Final evaluation metrics: {final_metrics}")
    if "wandb" in config.training.report_to:
        wandb.log(final_metrics, step=global_step)
        wandb.finish()


if __name__ == "__main__":
    main()
