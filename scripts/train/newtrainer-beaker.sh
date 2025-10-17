#!/bin/bash

set -e

# Parse command line arguments
CONFIG="olmocr/train/configs/qwen25_vl_b100_x1_default.yaml"
DATASET="s3://ai2-oe-data/jakep/olmocr/olmOCR-mix-0825"
SKIP_DOCKER_BUILD=false
PREEMPTIBLE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --config)
            CONFIG="$2"
            shift 2
            ;;
        --dataset)
            DATASET="$2"
            shift 2
            ;;
        --skip-docker-build)
            SKIP_DOCKER_BUILD=true
            shift
            ;;
        --preemptible)
            PREEMPTIBLE=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--config CONFIG_PATH] [--dataset DATASET_PATH] [--skip-docker-build] [--preemptible]"
            exit 1
            ;;
    esac
done

echo "Using config: $CONFIG"
echo "Using dataset: $DATASET"

# Use conda environment Python if available, otherwise use system Python
if [ -n "$CONDA_PREFIX" ]; then
    PYTHON="$CONDA_PREFIX/bin/python"
    echo "Using conda Python from: $CONDA_PREFIX"
else
    PYTHON="python"
    echo "Warning: No conda environment detected, using system Python"
fi

# Get version from version.py
VERSION=$($PYTHON -c 'import olmocr.version; print(olmocr.version.VERSION)')
echo "OlmOCR version: $VERSION"

# Get first 10 characters of git hash
GIT_HASH=$(git rev-parse HEAD | cut -c1-10)
echo "Git hash: $GIT_HASH"

# Get current git branch name
GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
echo "Git branch: $GIT_BRANCH"

# Create full image tag
IMAGE_TAG="olmocr-train-${VERSION}-${GIT_HASH}"
echo "Building Docker image with tag: $IMAGE_TAG"

# Build and push Docker image if not skipping
if [ "$SKIP_DOCKER_BUILD" = false ]; then
    echo "Building Docker image..."
    docker build --platform linux/amd64 -f ./Dockerfile -t $IMAGE_TAG .
    
    # Push image to beaker
    echo "Trying to push image to Beaker..."
    if ! beaker image create --workspace ai2/oe-data-pdf --name $IMAGE_TAG $IMAGE_TAG 2>/dev/null; then
        echo "Warning: Beaker image with tag $IMAGE_TAG already exists. Using existing image."
    fi
else
    echo "Skipping Docker build as requested"
fi

# Get Beaker username
BEAKER_USER=$(beaker account whoami --format json | jq -r '.[0].name')
echo "Beaker user: $BEAKER_USER"

# Create Python script to run beaker experiment
cat << 'EOF' > /tmp/run_training_experiment.py
import sys
from beaker import Beaker, ExperimentSpec, TaskSpec, TaskContext, ResultSpec, TaskResources, ImageSource, Priority, Constraints, EnvVar, DataMount

# Get image tag, beaker user, git branch, git hash, config, dataset, and preemptible from command line
image_tag = sys.argv[1]
beaker_user = sys.argv[2]
git_branch = sys.argv[3]
git_hash = sys.argv[4]
config = sys.argv[5]
dataset = sys.argv[6]
preemptible = sys.argv[7] == "true"

# Initialize Beaker client
b = Beaker.from_env(default_workspace="ai2/olmocr")

# Build the training command
# Extract the dataset name from the S3 path for the local directory
dataset_name = dataset.rstrip('/').split('/')[-1]
commands = [
    "pip install .[train]",
    "pip install ninja",
    "pip install transformers==4.55.2",
    "pip install flash-attn==2.8.0.post2 --use-pep517 --no-build-isolation",
    "pip install s5cmd",
    f"s5cmd sync s3://ai2-oe-data/jakep/olmocr/qwen2.5-vl-7b-olmocrv4_1epoch_promptv4_mix1025_more_rotation_filtered-8372/* /data/models/qwen2.5-vl-7b-olmocrv4_1epoch_promptv4_mix1025_more_rotation_filtered-8372/",
    f"s5cmd sync s3://ai2-oe-data/jakep/olmocr/qwen2.5-vl-7b-olmocrv3_1epoch_prompt_first_rotation-7951/* /data/models/qwen2.5-vl-7b-olmocrv3_1epoch_prompt_first_rotation-7951",
    f"s5cmd sync 's3://ai2-oe-data/jakep/grpo_data_mixes/*' /data/jakep/grpo_data_mixes/",
    f"python -m olmocr.train.train --config {config}"
]

# Build task spec
task_spec = TaskSpec(
    name="olmocr-training",
    image=ImageSource(beaker=f"{beaker_user}/{image_tag}"),
    command=[
        "bash", "-c",
        " && ".join(commands)
    ],
    context=TaskContext(
        priority=Priority.normal,
        preemptible=preemptible,
    ),
    resources=TaskResources(
        gpu_count=1,
        shared_memory="10GiB"
    ),
    constraints=Constraints(cluster=["ai2/titan-cirrascale"]),
    result=ResultSpec(path="/noop-results"),
    env_vars=[
        EnvVar(name="LOG_FILTER_TYPE", value="local_rank0_only"),
        EnvVar(name="OMP_NUM_THREADS", value="8"),
        EnvVar(name="BEAKER_USER_ID", value=beaker_user),
        EnvVar(name="AWS_ACCESS_KEY_ID", secret="ALLENNLP_AWS_ACCESS_KEY_ID"),
        EnvVar(name="AWS_SECRET_ACCESS_KEY", secret="ALLENNLP_AWS_SECRET_ACCESS_KEY"),
        EnvVar(name="WANDB_API_KEY", secret="JAKE_WANDB_API_KEY")
    ],
    datasets=[
        DataMount.new(mount_path="/weka/oe-data-default", weka="oe-data-default"),
        DataMount.new(mount_path="/weka/oe-training-default", weka="oe-training-default"),
    ]
)

# Create experiment spec
experiment_spec = ExperimentSpec(
    description=f"OlmOCR Training Run - Branch: {git_branch}, Commit: {git_hash}",
    budget="ai2/oe-base",
    tasks=[task_spec],
)

# Create the experiment
experiment = b.experiment.create(spec=experiment_spec, workspace="ai2/olmocr")
print(f"Created training experiment: {experiment.id}")
print(f"View at: https://beaker.org/ex/{experiment.id}")
EOF

# Run the Python script to create the experiment
echo "Creating Beaker experiment..."
$PYTHON /tmp/run_training_experiment.py $IMAGE_TAG $BEAKER_USER $GIT_BRANCH $GIT_HASH "$CONFIG" "$DATASET" $PREEMPTIBLE

# Clean up temporary file
rm /tmp/run_training_experiment.py

echo "Training experiment submitted successfully!"