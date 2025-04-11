
import os
import json
import torch
import random
import multiprocessing

from hashlib import sha1
from logging import Logger
from datetime import datetime
from functools import partial
from transformers import AutoProcessor
from contextlib import contextmanager
from dataclasses import dataclass

from tempfile import TemporaryDirectory
from typing import Dict, Generator, List, Optional, TypeVar


from accelerate import Accelerator
from accelerate.utils import PrecisionType
from datasets import Dataset, DatasetDict, concatenate_datasets


from olmocr.train.dataloader import build_finetuning_dataset
from olmocr.train.dataprep import (
    batch_prepare_data_for_molmo_training,
    batch_prepare_data_for_qwen2_training,
)

from .core.cli import to_native_types
from .core.config import AwsConfig, DataConfig, SourceConfig, TrainConfig, WandbConfig
from .core.loggers import get_logger
from .core.paths import copy_dir, is_local
from .core.state import BeakerState

T = TypeVar("T")


def accelerator_to_dtype(accelerator: Accelerator) -> torch.dtype:
    pt = PrecisionType(accelerator.mixed_precision)
    if pt == PrecisionType.FP16:
        return torch.float16
    elif pt == PrecisionType.BF16:
        return torch.bfloat16
    elif pt == PrecisionType.FP8:
        return torch.float8_e4m3fn
    return torch.float32


def get_rawdataset_from_source(data_config: DataConfig, source: SourceConfig) -> Dataset:
    return build_finetuning_dataset(source.response_glob_path, pdf_cache_location=data_config.cache_location)


def make_dataset(config: TrainConfig, processor: AutoProcessor) -> tuple[Dataset, Dataset]:
    random.seed(config.train_data.seed)

    if "qwen" in config.model.name_or_path.lower():
        batch_fn = batch_prepare_data_for_qwen2_training
    elif "molmo" in config.model.name_or_path.lower():
        batch_fn = batch_prepare_data_for_molmo_training
    else:
        raise NotImplementedError("Model format not supported")

    # Retrieve the two target lengths from the first source for comparison
    first_source = config.train_data.sources[0]
    target_longest_image_dim = first_source.target_longest_image_dim
    target_anchor_text_len   = first_source.target_anchor_text_len

    # Verify that all sources have the same target lengths
    for source in config.train_data.sources:
        if source.target_longest_image_dim != target_longest_image_dim:
            raise ValueError(f"Inconsistent target_longest_image_dim found in source {source}")
        if source.target_anchor_text_len != target_anchor_text_len:
            raise ValueError(f"Inconsistent target_anchor_text_len found in source {source}")

    # Concatenate datasets first, unfortunately you can't apply the transform before concatenation due to the library
    train_dataset = concatenate_datasets([get_rawdataset_from_source(config.train_data, source) for source in config.train_data.sources])

    # Apply the transform to the concatenated dataset
    train_dataset = train_dataset.with_transform(
        partial(
            batch_fn,
            processor=processor,
            target_longest_image_dim=list(target_longest_image_dim),
            target_anchor_text_len=list(target_anchor_text_len),
        )
    )

    # Validation sets get put into a datasetdict so each can report a loss separately
    valid_dataset = DatasetDict(
        **{
            source.name: get_rawdataset_from_source(config.valid_data, source).with_transform(
                partial(
                    batch_fn,
                    processor=processor,
                    target_longest_image_dim=list(source.target_longest_image_dim),
                    target_anchor_text_len=list(source.target_anchor_text_len),
                )
            )
            for source in config.valid_data.sources
        }
    )

    return train_dataset, valid_dataset


def setup_environment(aws_config: Optional[AwsConfig] = None, wandb_config: Optional[WandbConfig] = None, **kwargs: str):
    multiprocessing.set_start_method("spawn", force=True)
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    os.environ["TRANSFORMERS_NO_ADVISORY_WARNINGS"] = "false"

    if wandb_config:
        os.environ["WANDB_WATCH"] = "false"

    for key, value in to_native_types(wandb_config or {}).items():
        if value is not None:
            os.environ[f"WANDB_{key.upper()}"] = str(value)

    for key, value in to_native_types(aws_config or {}).items():
        if value is not None:
            os.environ[f"AWS_{key.upper()}"] = str(value)

    os.environ.update(kwargs)


@dataclass
class RunName:
    run: str
    group: str

    @classmethod
    def get(cls, config: TrainConfig, accelerator: Optional[Accelerator] = None) -> "RunName":
        job_rank = f"-{accelerator.process_index}" if accelerator else ""

        if beaker_job_id := BeakerState().job_id:
            job_id = f"-{beaker_job_id}"
        else:
            job_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        (config_hash := sha1()).update(json.dumps(to_native_types(config)).encode())
        model_name = config.model.name_or_path.replace("/", "_")

        group_name = f"{model_name}-{config_hash.hexdigest()[:6]}"
        run_name = f"{group_name}{job_id}{job_rank}"
        return cls(group=group_name, run=run_name)


@contextmanager
def override_torch_threads(n: int):
    torch_num_threads = torch.get_num_threads()
    torch.set_num_threads(n)

    yield

    torch.set_num_threads(torch_num_threads)


@contextmanager
def temp_args(obj: T, **kwargs) -> Generator[T, None, None]:
    orig = {k: getattr(obj, k) for k in kwargs.keys()}
    for k, v in kwargs.items():
        setattr(obj, k, v)

    yield obj

    for k, v in orig.items():
        setattr(obj, k, v)


def log_trainable_parameters(model: torch.nn.Module, logger: Optional[Logger] = None):
    """
    Prints the number of trainable parameters in the model.
    """
    trainable_params = 0
    all_param        = 0
    for name, param in model.named_parameters():
        all_param += param.numel()
        if param.requires_grad:
            (logger or get_logger(__name__)).info(f"training with {name}")
            trainable_params += param.numel()

    (logger or get_logger(__name__)).info(
        "trainable params: %s || all params: %s || trainable%%: %s",
        f"{trainable_params:,}",
        f"{all_param:,}",
        f"{trainable_params / all_param:.2%}",
    )


class TruncatingCollator:
    def __init__(self, max_length: int):
        self.max_length = max_length

    def __call__(self, batch: List[Dict]) -> Dict:
        # Assert that we are only handling batch size 1 for now
        assert len(batch) == 1, "Only batch size 1 is supported for now"

        if "pixel_values" in batch[0]:
            # Qwen2 case
            truncated_input_ids = torch.tensor(batch[0]["input_ids"][: self.max_length]).unsqueeze(0)
            truncated_attention_mask = torch.tensor(batch[0]["attention_mask"][: self.max_length]).unsqueeze(0)
            truncated_labels = torch.tensor(batch[0]["labels"][: self.max_length]).unsqueeze(0)

            return {
                "input_ids": truncated_input_ids,
                "attention_mask": truncated_attention_mask,
                "labels": truncated_labels,
                "pixel_values": torch.tensor(batch[0]["pixel_values"]).unsqueeze(0),
                "image_grid_thw": torch.tensor(batch[0]["image_grid_thw"]).unsqueeze(0),
            }
        elif "image_input_idx" in batch[0]:
            # molmo case
            truncated_input_ids = batch[0]["input_ids"][: self.max_length].unsqueeze(0)
            truncated_attention_mask = batch[0]["attention_mask"][: self.max_length].unsqueeze(0)
            truncated_labels = batch[0]["labels"][: self.max_length].unsqueeze(0)

            return {
                "input_ids": truncated_input_ids,
                "attention_mask": truncated_attention_mask,
                "labels": truncated_labels,
                "images": batch[0]["images"].unsqueeze(0),
                "image_input_idx": batch[0]["image_input_idx"].unsqueeze(0),
                "image_masks": batch[0]["image_masks"].unsqueeze(0),
            }
        else:
            raise NotImplementedError()


@contextmanager
def get_local_dir(output_dir: str):
    with TemporaryDirectory() as tmp_dir:
        if is_local(output_dir):
            yield output_dir
        else:
            yield tmp_dir
            copy_dir(tmp_dir, output_dir)
