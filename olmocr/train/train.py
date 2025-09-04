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
import torch.distributed as dist
import wandb
from torch.amp import autocast
from torch.optim import AdamW
from torch.utils.data import ConcatDataset, DataLoader
from torch.utils.data.distributed import DistributedSampler
from tqdm import tqdm
from transformers import (
    AutoProcessor,
    Qwen2_5_VLForConditionalGeneration,
    Qwen2VLForConditionalGeneration,
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
    """Save model, optimizer, scheduler, and training state (FSDP-aware)."""
    # Only rank 0 performs file I/O when distributed
    is_distributed = dist.is_available() and dist.is_initialized()
    rank = dist.get_rank() if is_distributed else 0

    checkpoint_dir = None
    if rank == 0:
        checkpoint_dir = os.path.join(output_dir, f"checkpoint-{global_step}")
        os.makedirs(checkpoint_dir, exist_ok=True)
    if is_distributed:
        dist.barrier()

    # Determine if model is FSDP wrapped
    using_fsdp = False
    try:
        from torch.distributed.fsdp import FullyShardedDataParallel as FSDP
        using_fsdp = isinstance(model, FSDP)
    except Exception:
        using_fsdp = False

    if using_fsdp:
        from torch.distributed.fsdp import StateDictType, FullStateDictConfig, FullyShardedDataParallel as FSDP

        # Gather full state dict on rank 0
        with FSDP.state_dict_type(
            model,
            StateDictType.FULL_STATE_DICT,
            FullStateDictConfig(offload_to_cpu=True, rank0_only=True),
        ):
            full_state_dict = model.state_dict()
        if rank == 0:
            # Unwrap to underlying HF module for save_pretrained
            base_model = model.module
            base_model.save_pretrained(checkpoint_dir, state_dict=full_state_dict)
    else:
        if rank == 0:
            model.save_pretrained(checkpoint_dir)

    # Save optimizer and scheduler
    if using_fsdp:
        from torch.distributed.fsdp import FullyShardedDataParallel as FSDP

        optim_state = FSDP.optim_state_dict(model, optimizer)
        if rank == 0:
            torch.save(optim_state, os.path.join(checkpoint_dir, "optimizer.pt"))
    else:
        if rank == 0:
            torch.save(optimizer.state_dict(), os.path.join(checkpoint_dir, "optimizer.pt"))

    if rank == 0:
        torch.save(lr_scheduler.state_dict(), os.path.join(checkpoint_dir, "scheduler.pt"))
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
            checkpoints = sorted(
                [d for d in os.listdir(output_dir) if d.startswith("checkpoint-")],
                key=lambda x: int(x.split("-")[1]),
            )
            while len(checkpoints) > save_total_limit:
                oldest = checkpoints.pop(0)
                shutil.rmtree(os.path.join(output_dir, oldest))
                logger.info(f"Deleted old checkpoint: {oldest}")
    if is_distributed:
        dist.barrier()


def load_checkpoint(
    model_class: type,
    init_kwargs: Dict[str, Any],
    optimizer: torch.optim.Optimizer,
    lr_scheduler: Any,
    checkpoint_dir: str,
    device: torch.device,
) -> tuple[torch.nn.Module, Dict[str, Any]]:
    """Load model, optimizer, scheduler, and training state from checkpoint.

    Note: For FSDP, this loads the base HF model weights. Optimizer state
    should be loaded after wrapping with FSDP using FSDP.optim_state_dict_to_load.
    """
    model = model_class.from_pretrained(checkpoint_dir, **init_kwargs)
    model.to(device)

    opt_path = os.path.join(checkpoint_dir, "optimizer.pt")
    if os.path.exists(opt_path):
        try:
            optimizer.load_state_dict(torch.load(opt_path, map_location=device))
        except Exception:
            # Likely an FSDP optimizer state; will be handled after wrapping
            pass

    sched_path = os.path.join(checkpoint_dir, "scheduler.pt")
    if os.path.exists(sched_path):
        lr_scheduler.load_state_dict(torch.load(sched_path, map_location=device))

    state = torch.load(os.path.join(checkpoint_dir, "training_state.pt"), map_location=device)
    logger.info(
        f"Resumed from checkpoint: {checkpoint_dir} at epoch {state['epoch']:.2f}, step {state['global_step']}, samples seen {state['samples_seen']}"
    )
    return model, state


def evaluate_model(
    model: torch.nn.Module,
    eval_dataloaders: Dict[str, DataLoader],
    device: torch.device,
) -> Dict[str, float]:
    """Evaluate on all eval datasets and return average loss per dataset."""
    model.eval()
    eval_metrics = {}

    is_distributed = dist.is_available() and dist.is_initialized()

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

        if is_distributed:
            # Sum losses and counts across ranks
            loss_tensor = torch.tensor([total_loss], dtype=torch.float64, device=device)
            count_tensor = torch.tensor([num_batches], dtype=torch.float64, device=device)
            dist.all_reduce(loss_tensor, op=dist.ReduceOp.SUM)
            dist.all_reduce(count_tensor, op=dist.ReduceOp.SUM)
            total_loss = float(loss_tensor.item())
            num_batches = int(count_tensor.item())

        avg_loss = total_loss / num_batches if num_batches > 0 else 0.0
        eval_metrics[f"eval_{dataset_name}_loss"] = avg_loss
        if (not is_distributed) or dist.get_rank() == 0:
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
    sampler: Optional[torch.utils.data.Sampler] = None,
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
        shuffle=(sampler is None),
        sampler=sampler,
        collate_fn=data_collator,
        num_workers=config.training.dataloader_num_workers,
        drop_last=config.training.dataloader_drop_last,
        worker_init_fn=seed_worker,
        generator=None if sampler is not None else epoch_generator,
        pin_memory=True,
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

    # Distributed init (torchrun)
    is_distributed = False
    local_rank = int(os.environ.get("LOCAL_RANK", "-1"))
    world_size = int(os.environ.get("WORLD_SIZE", "1"))
    rank = int(os.environ.get("RANK", "0"))
    if world_size > 1 or local_rank != -1:
        is_distributed = True
        if torch.cuda.is_available():
            torch.cuda.set_device(local_rank)
        dist.init_process_group(backend="nccl")
        if rank == 0:
            logger.info(f"Initialized distributed: rank={rank}, local_rank={local_rank}, world_size={world_size}")

    # Initialize wandb if reporting to it (rank 0 only)
    if (not is_distributed or rank == 0) and ("wandb" in config.training.report_to):
        wandb.init(project=config.project_name, name=config.run_name, config=config.to_dict())

    # Load processor for tokenization
    logger.info(f"Loading processor: {config.model.name}")
    processor = AutoProcessor.from_pretrained(
        config.model.name,
    )

    # Model init kwargs to reuse for loading checkpoints
    model_init_kwargs = {
        "torch_dtype": getattr(torch, config.model.torch_dtype) if config.model.torch_dtype != "auto" else "auto",
        "device_map": None if is_distributed else config.model.device_map,
        "trust_remote_code": config.model.trust_remote_code,
        "attn_implementation": config.model.attn_implementation if config.model.use_flash_attention else None,
    }

    # Load model
    logger.info(f"Loading model: {config.model.name}")
    if "Qwen2.5-VL" in config.model.name:
        model_class = Qwen2_5_VLForConditionalGeneration
        model = model_class.from_pretrained(config.model.name, **model_init_kwargs)
    elif "Qwen2-VL" in config.model.name:
        model_class = Qwen2VLForConditionalGeneration
        model = model_class.from_pretrained(config.model.name, **model_init_kwargs)
    else:
        raise NotImplementedError()

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
    if torch.cuda.is_available():
        device = torch.device(f"cuda:{local_rank}") if is_distributed else torch.device("cuda")
    else:
        device = torch.device("cpu")
    model.to(device)

    # Apply torch compile if enabled (skip with distributed/FSDP)
    if (not is_distributed) and config.training.torch_compile:
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
        if is_distributed:
            raise NotImplementedError("Muon optimizer is not supported with FSDP in this training script.")
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
    per_device_bs = config.training.per_device_train_batch_size
    grad_accum = config.training.gradient_accumulation_steps
    global_effective_batch = per_device_bs * (world_size if (dist.is_available() and dist.is_initialized()) else 1) * grad_accum
    num_update_steps_per_epoch = math.ceil(len(train_dataset) / global_effective_batch)
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

    # Resume from checkpoint if available (distributed-aware)
    global_step = 0
    samples_seen = 0
    best_metric = float("inf") if not config.training.greater_is_better else -float("inf")

    if found_resumable_checkpoint:
        if is_distributed:
            # In distributed, load model weights before wrapping, then load optimizer/scheduler after creation
            model = model_class.from_pretrained(found_resumable_checkpoint, **model_init_kwargs)
            model.to(device)
            state = torch.load(os.path.join(found_resumable_checkpoint, "training_state.pt"), map_location="cpu")
            global_step = state.get("global_step", 0)
            best_metric = state.get("best_metric", best_metric)
            samples_seen = state.get("samples_seen", 0)
            if rank == 0:
                logger.info(
                    f"Resuming (FSDP) from {found_resumable_checkpoint}: epoch {state.get('epoch', 0):.2f}, step {global_step}, samples {samples_seen}"
                )
        else:
            model, state = load_checkpoint(
                model_class, model_init_kwargs, optimizer, lr_scheduler, found_resumable_checkpoint, device
            )
            global_step = state["global_step"]
            best_metric = state["best_metric"]
            samples_seen = state["samples_seen"]

    

    # If distributed, wrap with FSDP after potential weight load
    if is_distributed:
        from torch.distributed.fsdp import (
            FullyShardedDataParallel as FSDP,
            MixedPrecision,
            ShardingStrategy,
        )
        from functools import partial
        from torch.distributed.fsdp.wrap import size_based_auto_wrap_policy

        mp_dtype = torch.bfloat16 if (str(getattr(model, 'dtype', 'torch.float32')) == 'torch.bfloat16' or config.model.torch_dtype == 'bfloat16') else torch.float16
        mixed_precision = MixedPrecision(param_dtype=mp_dtype, reduce_dtype=mp_dtype, buffer_dtype=mp_dtype)
        auto_wrap_policy = partial(size_based_auto_wrap_policy, min_num_params=10_000_000)

        model = FSDP(
            model,
            sharding_strategy=ShardingStrategy.FULL_SHARD,
            auto_wrap_policy=auto_wrap_policy,
            mixed_precision=mixed_precision,
            device_id=device if device.type == 'cuda' else None,
        )

        # Load optimizer/scheduler states for FSDP resumes now that model and optimizer are set up
        if found_resumable_checkpoint:
            opt_path = os.path.join(found_resumable_checkpoint, "optimizer.pt")
            if os.path.exists(opt_path):
                try:
                    optim_state = torch.load(opt_path, map_location="cpu")
                    optim_state = FSDP.optim_state_dict_to_load(optimizer, optim_state, model)
                    optimizer.load_state_dict(optim_state)
                    if rank == 0:
                        logger.info("Loaded optimizer state (FSDP)")
                except Exception as e:
                    if rank == 0:
                        logger.warning(f"Could not load FSDP optimizer state: {e}")
            sched_path = os.path.join(found_resumable_checkpoint, "scheduler.pt")
            if os.path.exists(sched_path):
                lr_scheduler.load_state_dict(torch.load(sched_path, map_location="cpu"))
                if rank == 0:
                    logger.info("Loaded scheduler state")

    # Create dataloaders - use epoch 0 initially (will be recreated with proper epoch if resuming)
    current_epoch_num = int(samples_seen / len(train_dataset)) if samples_seen > 0 else 0
    if is_distributed:
        train_sampler = DistributedSampler(
            train_dataset,
            num_replicas=world_size,
            rank=rank,
            shuffle=True,
            seed=config.training.data_seed or 42,
            drop_last=config.training.dataloader_drop_last,
        )
        train_sampler.set_epoch(current_epoch_num)
    else:
        train_sampler = None
    train_dataloader = create_train_dataloader(
        train_dataset,
        config,
        data_collator,
        seed_worker,
        epoch_num=current_epoch_num,
        sampler=train_sampler,
    )

    eval_dataloaders = {}
    for name, dataset in eval_datasets.items():
        if is_distributed:
            eval_sampler = DistributedSampler(dataset, num_replicas=world_size, rank=rank, shuffle=False, drop_last=False)
        else:
            eval_sampler = None
        eval_dataloaders[name] = DataLoader(
            dataset,
            batch_size=config.training.per_device_eval_batch_size,
            shuffle=False if eval_sampler is not None else False,
            sampler=eval_sampler,
            collate_fn=data_collator,
            num_workers=config.training.dataloader_num_workers,
            drop_last=False,
            pin_memory=True,
        )

    # Always evaluate on start
    metrics = evaluate_model(model, eval_dataloaders, device)
    if (not is_distributed) or rank == 0:
        logger.info(f"Initial evaluation: {metrics}")
        if "wandb" in config.training.report_to:
            wandb.log(metrics, step=global_step)

    # Main training loop
    current_epoch = samples_seen / len(train_dataset)
    if (not is_distributed) or rank == 0:
        logger.info(
            f"Starting training from epoch {current_epoch:.2f} (step {global_step}, samples {samples_seen}) to {config.training.num_train_epochs} epochs"
        )
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
        if (not is_distributed) and samples_seen > 0:
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
        
        # Create progress bar (rank 0 only)
        pbar = tqdm(total=max_train_samples - samples_seen, desc=f"Training from step {global_step}", unit="samples") if ((not is_distributed) or rank == 0) else None

        micro_count = 0
        while samples_seen < max_train_samples and global_step < max_train_steps:
            try:
                batch = next(epoch_iterator)
            except StopIteration:
                # End of epoch, create new dataloader with fresh shuffle
                current_epoch = samples_seen / len(train_dataset)
                if (not is_distributed) or rank == 0:
                    logger.info(f"Completed epoch {current_epoch:.2f}")
                
                # Increment epoch number for new shuffle seed
                current_epoch_num += 1
                
                # Recreate dataloader with new generator for fresh shuffle
                if is_distributed:
                    train_sampler.set_epoch(current_epoch_num)
                train_dataloader = create_train_dataloader(
                    train_dataset,
                    config,
                    data_collator,
                    seed_worker,
                    epoch_num=current_epoch_num,
                    sampler=train_sampler,
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
            # Increment seen samples in global terms for progress/termination
            samples_seen += config.training.per_device_train_batch_size * (world_size if is_distributed else 1)

            micro_count += 1

            # Update progress bar
            if pbar is not None:
                pbar.update(config.training.per_device_train_batch_size * (world_size if is_distributed else 1))

            # Check if we should do a gradient update
            if (micro_count % grad_accum == 0) or samples_seen >= max_train_samples:
                # Clip gradients (FSDP-aware)
                try:
                    from torch.distributed.fsdp import FullyShardedDataParallel as FSDP
                    if isinstance(model, FSDP):
                        FSDP.clip_grad_norm_(model.parameters(), config.training.max_grad_norm)
                    else:
                        torch.nn.utils.clip_grad_norm_(model.parameters(), config.training.max_grad_norm)
                except Exception:
                    torch.nn.utils.clip_grad_norm_(model.parameters(), config.training.max_grad_norm)

                # Step optimizer and scheduler
                optimizer.step()
                lr_scheduler.step()
                optimizer.zero_grad()

                global_step += 1
                current_epoch = samples_seen / len(train_dataset)

                # Update progress bar with current stats
                if pbar is not None:
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
                    if (not is_distributed) or rank == 0:
                        logger.info(f"Step {global_step}: epoch={current_epoch:.3f}, loss={avg_train_loss:.4f}, lr={lr_scheduler.get_last_lr()[0]:.2e}")
                        if "wandb" in config.training.report_to:
                            wandb.log(logs, step=global_step)

                    accumulated_loss = 0.0
                    num_losses_accumulated = 0

                # Evaluation
                if config.training.eval_steps > 0 and global_step % config.training.eval_steps == 0 and global_step > 0:
                    metrics = evaluate_model(model, eval_dataloaders, device)
                    if (not is_distributed) or rank == 0:
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
        if pbar is not None:
            pbar.close()

    # Save the final checkpoint with step number
    if (not is_distributed) or rank == 0:
        logger.info(f"Saving final checkpoint at step {global_step}...")
    save_checkpoint(model, optimizer, lr_scheduler, current_epoch, global_step, samples_seen, best_metric, full_output_dir, config.training.save_total_limit)

    # Log final training state
    final_epoch = samples_seen / len(train_dataset)
    if (not is_distributed) or rank == 0:
        logger.info(f"Training completed at epoch {final_epoch:.3f}, step {global_step}, samples {samples_seen}")

    # Final evaluation
    final_metrics = evaluate_model(model, eval_dataloaders, device)
    if (not is_distributed) or rank == 0:
        logger.info(f"Final evaluation metrics: {final_metrics}")
        if "wandb" in config.training.report_to:
            wandb.log(final_metrics, step=global_step)
            wandb.finish()

    # Distributed cleanup
    if is_distributed:
        dist.barrier()
        dist.destroy_process_group()


if __name__ == "__main__":
    main()
