"""Configuration system for OlmOCR training using YAML and dataclasses."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from omegaconf import OmegaConf


@dataclass
class PipelineStepConfig:
    """Base configuration for pipeline steps."""

    name: str
    enabled: bool = True


@dataclass
class FrontMatterParserConfig(PipelineStepConfig):
    """Configuration for FrontMatterParser step."""

    name: str = "FrontMatterParser"
    use_page_response_class: bool = True  # Whether to use PageResponse dataclass


@dataclass
class PDFRendererConfig(PipelineStepConfig):
    """Configuration for PDFRenderer step."""

    name: str = "PDFRenderer"
    target_longest_image_dim: int = 1024


@dataclass
class StaticLengthDocumentAnchoringConfig(PipelineStepConfig):
    """Configuration for StaticLengthDocumentAnchoring step."""

    name: str = "StaticLengthDocumentAnchoring"
    target_anchor_text_len: int = 6000


@dataclass
class FinetuningPromptConfig(PipelineStepConfig):
    """Configuration for FinetuningPrompt step."""

    name: str = "FinetuningPrompt"


@dataclass
class NewYamlFinetuningPromptWithAnchoringConfig(PipelineStepConfig):
    """Configuration for NewYamlFinetuningPromptWithAnchoring step."""

    name: str = "NewYamlFinetuningPromptWithAnchoring"


@dataclass
class NewYamlFinetuningPromptWithNoAnchoringConfig(PipelineStepConfig):
    """Configuration for NewYamlFinetuningPromptWithNoAnchoring step."""

    name: str = "NewYamlFinetuningPromptWithNoAnchoring"


@dataclass
class FrontMatterOutputFormatConfig(PipelineStepConfig):
    """Configuration for FrontMatterOutputFormat step."""

    name: str = "FrontMatterOutputFormat"


@dataclass
class JSONOutputFormatConfig(PipelineStepConfig):
    """Configuration for JSONOutputFormat step."""

    name: str = "JSONOutputFormat"


@dataclass
class InstructUserMessagesConfig(PipelineStepConfig):
    """Configuration for InstructUserMessages step."""

    name: str = "InstructUserMessages"
    prompt_first: bool = False


@dataclass
class LatexBracketNormalizerConfig(PipelineStepConfig):
    """Configuration for LatexBracketNormalizer step."""

    name: str = "LatexBracketNormalizer"


@dataclass
class ReformatLatexBoldItalicConfig(PipelineStepConfig):
    """Configuration for ReformatLatexBoldItalic step."""

    name: str = "ReformatLatexBoldItalic"


@dataclass
class TokenizerStepConfig(PipelineStepConfig):
    """Configuration for Tokenizer step."""

    name: str = "Tokenizer"
    masking_index: int = -100
    end_of_message_token: str = "<|im_end|>"


@dataclass
class RandomTokenFlipperConfig(PipelineStepConfig):
    """Configuration for RandomTokenFlipper step."""

    name: str = "RandomTokenFlipper"
    token_flip_rate: float = 1e-4
    masking_index: int = -100


@dataclass
class FilterOutRotatedDocumentsConfig(PipelineStepConfig):
    """Configuration for FilterOutRotatedDocuments step."""

    name: str = "FilterOutRotatedDocuments"


@dataclass
class DatasetTextRuleFilterConfig(PipelineStepConfig):
    """Configuration for DatasetTextRuleFilter step."""

    name: str = "DatasetTextRuleFilter"


@dataclass
class RotationAugmentationConfig(PipelineStepConfig):
    """Configuration for RotationAugmentation step."""

    name: str = "RotationAugmentation"
    probability: float = 0.5


@dataclass
class AugraphyBasicAugmentationsConfig(PipelineStepConfig):
    """Configuration for AugraphyBasicAugmentations step."""

    name: str = "AugraphyBasicAugmentations"
    probability: float = 0.5  # Overall probability of applying any augmentation


@dataclass
class DatasetItemConfig:
    """Configuration for a single dataset item."""

    root_dir: str
    pipeline: List[Dict[str, Any]] = field(default_factory=list)

    # Optional sampling
    max_samples: Optional[int] = None


@dataclass
class DatasetConfig:
    """Configuration for dataset and data loading."""

    train: List[Dict[str, Any]] = field(default_factory=list)
    eval: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ModelConfig:
    """Configuration for model."""

    name: str = "Qwen/Qwen2.5-VL-7B-Instruct"
    trust_remote_code: bool = False

    # Model initialization
    load_in_8bit: bool = False
    load_in_4bit: bool = False
    device_map: Any = "auto"  # Can be string or dict
    torch_dtype: str = "auto"  # "auto", "float16", "bfloat16", "float32"

    # Flash attention
    use_flash_attention: bool = True
    attn_implementation: Optional[str] = None  # "flash_attention_2", "sdpa", "eager"

    # Model modifications
    freeze_vision_tower: bool = False
    freeze_language_model: bool = False

    # LoRA configuration (optional)
    use_lora: bool = False
    lora_rank: int = 8
    lora_alpha: int = 32
    lora_dropout: float = 0.1
    lora_target_modules: List[str] = field(default_factory=lambda: ["q_proj", "v_proj", "k_proj", "o_proj"])
    lora_modules_to_save: Optional[List[str]] = None


@dataclass
class TrainingConfig:
    """Configuration for training parameters."""

    output_dir: str = "./outputs"
    num_train_epochs: int = 1
    per_device_train_batch_size: int = 1
    per_device_eval_batch_size: int = 1
    gradient_accumulation_steps: int = 8

    # Learning rate and scheduler
    learning_rate: float = 2e-5
    lr_scheduler_type: str = "cosine"
    warmup_ratio: float = 0.1
    lr_scheduler_kwargs: Dict[str, Any] = field(default_factory=dict)

    # Optimization
    optim: str = "adamw_torch"  # "adamw_torch", "muon"
    adam_beta1: float = 0.9
    adam_beta2: float = 0.999
    adam_epsilon: float = 1e-8
    weight_decay: float = 0.01
    max_grad_norm: float = 1.0

    # Muon optimizer specific settings
    muon_momentum: float = 0.95
    muon_lr_multiplier_head: float = 11.0  # Learning rate multiplier for head parameters
    muon_lr_multiplier_embed: float = 30.0  # Learning rate multiplier for embedding parameters
    muon_lr_multiplier_scalar: float = 2.0  # Learning rate multiplier for scalar parameters

    # Gradient checkpointing
    gradient_checkpointing: bool = False
    gradient_checkpointing_kwargs: Dict[str, Any] = field(default_factory=lambda: {"use_reentrant": False})

    # Evaluation and checkpointing
    evaluation_strategy: str = "steps"
    eval_steps: int = 500
    save_strategy: str = "steps"
    save_steps: int = 500
    save_total_limit: int = 3
    load_best_model_at_end: bool = True
    metric_for_best_model: str = "eval_loss"
    greater_is_better: bool = False

    # Logging
    logging_dir: Optional[str] = None
    logging_strategy: str = "steps"
    logging_steps: int = 10
    logging_first_step: bool = True
    report_to: List[str] = field(default_factory=lambda: ["wandb"])

    # Force seeds to a consistent value for reproducibility
    seed: int = 42
    data_seed: Optional[int] = 42

    # Performance
    dataloader_drop_last: bool = True
    dataloader_num_workers: int = 16

    # Data collator settings
    collator_max_token_len: Optional[int] = None
    remove_unused_columns: bool = False  # Important for custom datasets

    # Torch compile settings
    torch_compile: bool = False
    torch_compile_backend: str = "inductor"  # "inductor", "aot_eager", "cudagraphs", etc.
    torch_compile_mode: str = "default"  # "default", "reduce-overhead", "max-autotune"
    torch_compile_fullgraph: bool = False
    torch_compile_dynamic: bool = False

    # Early stopping
    use_early_stopping: bool = False
    early_stopping_patience: int = 3
    early_stopping_threshold: float = 0.0


@dataclass
class Config:
    """Main configuration class that combines all sub-configs."""

    model: ModelConfig
    dataset: DatasetConfig
    training: TrainingConfig

    # Environment
    project_name: str = "olmocr-training"
    run_name: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    notes: Optional[str] = None

    # Experiment tracking
    experiment_tracker: str = "tensorboard"  # "tensorboard", "wandb", "mlflow"
    wandb_project: Optional[str] = None
    wandb_entity: Optional[str] = None

    # Distributed training
    distributed: bool = False
    local_rank: int = -1

    @classmethod
    def from_yaml(cls, yaml_path: str | Path) -> "Config":
        """Load configuration from YAML file."""
        yaml_path = Path(yaml_path)
        if not yaml_path.exists():
            raise FileNotFoundError(f"Config file not found: {yaml_path}")

        # Load YAML with OmegaConf for better features
        with open(yaml_path, "r") as f:
            yaml_content = yaml.safe_load(f)

        # Create OmegaConf config for interpolation and validation
        cfg = OmegaConf.create(yaml_content)

        # Resolve any interpolations
        OmegaConf.resolve(cfg)

        # Convert to dict and create dataclass
        cfg_dict = OmegaConf.to_container(cfg, resolve=True)

        # Create sub-configs
        model_cfg = ModelConfig(**cfg_dict.get("model", {}))
        dataset_cfg = DatasetConfig(**cfg_dict.get("dataset", {}))
        training_cfg = TrainingConfig(**cfg_dict.get("training", {}))

        # Create main config
        main_cfg_dict = {k: v for k, v in cfg_dict.items() if k not in ["model", "dataset", "training"]}

        return cls(model=model_cfg, dataset=dataset_cfg, training=training_cfg, **main_cfg_dict)

    def to_yaml(self, yaml_path: str | Path) -> None:
        """Save configuration to YAML file."""
        yaml_path = Path(yaml_path)
        yaml_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert to OmegaConf for nice YAML output
        cfg = OmegaConf.structured(self)

        with open(yaml_path, "w") as f:
            OmegaConf.save(cfg, f)

    def validate(self) -> None:
        """Validate configuration values."""
        # Dataset validation - check all train and eval datasets
        for split_name, datasets in [("train", self.dataset.train), ("eval", self.dataset.eval)]:
            for i, dataset_cfg in enumerate(datasets):
                root_dir = dataset_cfg.get("root_dir")
                if not root_dir:
                    raise ValueError(f"Missing root_dir for {split_name} dataset {i}")
                if not os.path.exists(root_dir):
                    raise ValueError(f"Dataset root directory does not exist: {root_dir}")

        # Model validation
        if self.model.load_in_8bit and self.model.load_in_4bit:
            raise ValueError("Cannot load in both 8bit and 4bit")

        # Output directory
        Path(self.training.output_dir).mkdir(parents=True, exist_ok=True)

        # Logging directory
        if self.training.logging_dir is None:
            self.training.logging_dir = os.path.join(self.training.output_dir, "logs")
        Path(self.training.logging_dir).mkdir(parents=True, exist_ok=True)

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        cfg = OmegaConf.structured(self)
        return OmegaConf.to_container(cfg, resolve=True)

    def get_pipeline_steps(self, pipeline_config: List[Dict[str, Any]], processor=None):
        """Create actual pipeline step instances from pipeline configuration.

        Args:
            pipeline_config: List of pipeline step configurations
            processor: The model processor (required for Tokenizer step)

        Returns:
            List of initialized pipeline step instances
        """
        from olmocr.prompts.prompts import PageResponse
        from olmocr.train.dataloader import (
            AugraphyBasicAugmentations,
            DatasetTextRuleFilter,
            FilterOutRotatedDocuments,
            FinetuningPrompt,
            FrontMatterOutputFormat,
            FrontMatterParser,
            InstructUserMessages,
            JSONOutputFormat,
            LatexBracketNormalizer,
            NewYamlFinetuningPromptWithAnchoring,
            NewYamlFinetuningPromptWithNoAnchoring,
            PDFRenderer,
            RandomTokenFlipper,
            ReformatLatexBoldItalic,
            RotationAugmentation,
            StaticLengthDocumentAnchoring,
            Tokenizer,
        )

        steps = []
        for step_config in pipeline_config:
            if not step_config.get("enabled", True):
                continue

            step_name = step_config["name"]

            if step_name == "FrontMatterParser":
                # Handle both old and new config format
                if "front_matter_class" in step_config:
                    front_matter_class = PageResponse if step_config["front_matter_class"] == "PageResponse" else None
                else:
                    front_matter_class = PageResponse if step_config.get("use_page_response_class", True) else None
                steps.append(FrontMatterParser(front_matter_class=front_matter_class))

            elif step_name == "PDFRenderer":
                steps.append(PDFRenderer(target_longest_image_dim=step_config.get("target_longest_image_dim", 1024)))

            elif step_name == "StaticLengthDocumentAnchoring":
                steps.append(StaticLengthDocumentAnchoring(target_anchor_text_len=step_config.get("target_anchor_text_len", 6000)))

            elif step_name == "FinetuningPrompt":
                steps.append(FinetuningPrompt())

            elif step_name == "NewYamlFinetuningPromptWithAnchoring":
                steps.append(NewYamlFinetuningPromptWithAnchoring())

            elif step_name == "NewYamlFinetuningPromptWithNoAnchoring":
                steps.append(NewYamlFinetuningPromptWithNoAnchoring())

            elif step_name == "JSONOutputFormat":
                steps.append(JSONOutputFormat())

            elif step_name == "FrontMatterOutputFormat":
                steps.append(FrontMatterOutputFormat())

            elif step_name == "InstructUserMessages":
                steps.append(InstructUserMessages(prompt_first=step_config.get("prompt_first", False)))

            elif step_name == "LatexBracketNormalizer":
                steps.append(LatexBracketNormalizer())

            elif step_name == "Tokenizer":
                if processor is None:
                    raise ValueError("Processor must be provided for Tokenizer step")
                steps.append(
                    Tokenizer(
                        processor=processor,
                        masking_index=step_config.get("masking_index", -100),
                        end_of_message_token=step_config.get("end_of_message_token", "<|im_end|>"),
                    )
                )
            elif step_name == "RandomTokenFlipper":
                if processor is None:
                    raise ValueError("Processor must be provided for RandomTokenFlipper step (to get valid tokens)")
                tokenizer = processor.tokenizer

                # Get all special token IDs to exclude
                special_token_ids = set()
                for token in tokenizer.all_special_tokens:
                    special_token_ids.add(tokenizer.convert_tokens_to_ids(token))

                # Get all token IDs that are not special tokens
                valid_token_ids = []
                for token_id in range(len(tokenizer)):
                    if token_id not in special_token_ids:
                        valid_token_ids.append(token_id)

                steps.append(
                    RandomTokenFlipper(
                        valid_token_ids=valid_token_ids,
                        token_flip_rate=step_config.get("token_flip_rate", 1e-4),
                        masking_index=step_config.get("masking_index", -100),
                    )
                )

            elif step_name == "FilterOutRotatedDocuments":
                steps.append(FilterOutRotatedDocuments())

            elif step_name == "DatasetTextRuleFilter":
                steps.append(DatasetTextRuleFilter())

            elif step_name == "RotationAugmentation":
                steps.append(RotationAugmentation(probability=step_config.get("probability", 0.5)))

            elif step_name == "AugraphyBasicAugmentations":
                steps.append(AugraphyBasicAugmentations(probability=step_config.get("probability", 0.5)))

            elif step_name == "ReformatLatexBoldItalic":
                steps.append(ReformatLatexBoldItalic())

            else:
                raise ValueError(f"Unknown pipeline step: {step_name}")

        return steps


def create_default_config() -> Config:
    """Create a default configuration."""
    return Config(model=ModelConfig(), dataset=DatasetConfig(), training=TrainingConfig())


if __name__ == "__main__":
    # Example: Create and save default config
    config = create_default_config()
    config.to_yaml("configs/default_config.yaml")
    print("Default config saved to configs/default_config.yaml")

    # Example: Load from YAML
    # loaded_config = Config.from_yaml("configs/default_config.yaml")
    # print(loaded_config)
