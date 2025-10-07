#!/bin/bash

set -e

# Parse beaker-specific arguments
SKIP_DOCKER_BUILD=false
PREEMPTIBLE=false
EXP_NAME=""

# Store all arguments to pass to python command
PYTHON_ARGS=()

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-docker-build)
            SKIP_DOCKER_BUILD=true
            shift
            ;;
        --preemptible)
            PREEMPTIBLE=true
            shift
            ;;
        --name)
            EXP_NAME="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [beaker-options] [grpo-training-options]"
            echo ""
            echo "Beaker-specific options:"
            echo "  --skip-docker-build            Skip Docker build"
            echo "  --preemptible                  Use preemptible instances"
            echo "  --name NAME                    Experiment name (used in output directory)"
            echo ""
            echo "All other arguments are forwarded to python -m olmocr.train.grpo_train"
            echo "Run 'python -m olmocr.train.grpo_train --help' to see available training options"
            exit 0
            ;;
        *)
            # Store all other arguments to pass to python command
            PYTHON_ARGS+=("$1")
            shift
            ;;
    esac
done

echo "Preemptible: $PREEMPTIBLE"
echo "Skip Docker Build: $SKIP_DOCKER_BUILD"
echo "Arguments to forward: ${PYTHON_ARGS[@]}"

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
IMAGE_TAG="olmocr-grpo-${VERSION}-${GIT_HASH}"
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
cat << 'EOF' > /tmp/run_grpo_experiment.py
import sys
import shlex
import os
from beaker import Beaker, ExperimentSpec, TaskSpec, TaskContext, ResultSpec, TaskResources, ImageSource, Priority, Constraints, EnvVar, DataMount

# Get parameters from command line
image_tag = sys.argv[1]
beaker_user = sys.argv[2]
git_branch = sys.argv[3]
git_hash = sys.argv[4]
preemptible = sys.argv[5] == "true"
exp_name = sys.argv[6]  # Empty string if not provided
# All remaining arguments are the python command arguments
python_args = sys.argv[7:]

# Initialize Beaker client
b = Beaker.from_env(default_workspace="ai2/olmocr")

# Build the training command
commands = [
    # Install dependencies
    "pip install .[train]",
    "pip install trl==0.22.2 wandb",
    "pip install transformers==4.55.2",  # Updated for GRPO compatibility
    "pip install flash-attn==2.8.0.post2 --no-build-isolation",
    "pip install vllm==v0.10.1.1",
    "pip install s5cmd",
    
    # Sync the bench data from S3
    "echo 'Syncing bench data from S3...'",
    "mkdir -p /data/olmOCR-bench",
    "s5cmd sync 's3://ai2-oe-data/jakep/olmocr/olmOCR-bench-snapshot-082225/*' /data/olmOCR-bench/",
    "s5cmd sync 's3://ai2-oe-data/jakep/grpo_data_mixes/*' /data/jakep/grpo_data_mixes/",
    
    # Build GRPO training command
    "echo 'Starting GRPO training...'",
]

# Check if model_name is an S3 path and handle it
model_sync_commands = []
modified_args = list(python_args)
for i in range(len(modified_args)):
    if modified_args[i] == "--model_name" and i + 1 < len(modified_args):
        model_path = modified_args[i + 1].rstrip('/')
        if model_path.startswith("s3://"):
            # Extract checkpoint name from S3 path (last part of path)
            checkpoint_name = model_path.split('/')[-1]
            local_model_path = f"/data/models/{checkpoint_name}"
            
            # Create sync commands
            model_sync_commands = [
                f"echo 'Syncing model from S3: {model_path}'",
                "mkdir -p /data/models",
                f"s5cmd sync '{model_path}/*' '{local_model_path}/'",
            ]
            
            # Replace S3 path with local path in arguments
            modified_args[i + 1] = local_model_path
        break

# Add model sync commands if needed
commands.extend(model_sync_commands)

# Build the python command with forwarded arguments
# Add default paths if not provided in arguments
grpo_cmd = ["python -m olmocr.train.grpo_train"]

# Check if certain required arguments are in the provided args, add defaults if not
arg_str = " ".join(modified_args)
if "--train_bench_data_folder" not in arg_str:
    grpo_cmd.append("--train_bench_data_folder /data/olmOCR-bench/bench_data")
if "--eval_bench_data_folder" not in arg_str:
    grpo_cmd.append("--eval_bench_data_folder /data/olmOCR-bench/bench_data")
if "--output_dir" not in arg_str:
    output_dir = "/weka/oe-training-default/jakep/olmocr-grpo-checkpoints"
    # Build subdirectory based on exp_name and BEAKER_WORKLOAD_ID
    beaker_workload_id = os.environ.get("BEAKER_WORKLOAD_ID")
    if exp_name and beaker_workload_id:
        output_dir = f"{output_dir}/{exp_name}-{beaker_workload_id}"
    elif beaker_workload_id:
        output_dir = f"{output_dir}/{beaker_workload_id}"
    elif exp_name:
        output_dir = f"{output_dir}/{exp_name}"
    grpo_cmd.append(f"--output_dir {output_dir}")

# Add all the (possibly modified) arguments
grpo_cmd.extend(modified_args)

# Add the GRPO command to the commands list
commands.append(" ".join(grpo_cmd))

# Extract model name from arguments if provided (for description)
model_name = "Unknown"
for i, arg in enumerate(modified_args):
    if arg in ["--model_name", "--model"]:
        if i + 1 < len(modified_args):
            model_name = modified_args[i + 1]
            break

# Build task spec
task_spec = TaskSpec(
    name="olmocr-grpo-training",
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
        EnvVar(name="WANDB_API_KEY", secret="JAKE_WANDB_API_KEY"),
    ],
    datasets=[
        DataMount.new(mount_path="/weka/oe-data-default", weka="oe-data-default"),
        DataMount.new(mount_path="/weka/oe-training-default", weka="oe-training-default"),
    ]
)

# Create experiment spec
experiment_spec = ExperimentSpec(
    description=f"OlmOCR GRPO Training - Model: {model_name}, Branch: {git_branch}, Commit: {git_hash}",
    budget="ai2/oe-base",
    tasks=[task_spec],
)

# Create the experiment
experiment = b.experiment.create(spec=experiment_spec, workspace="ai2/olmocr")
print(f"Created GRPO training experiment: {experiment.id}")
print(f"View at: https://beaker.org/ex/{experiment.id}")
EOF

# Run the Python script to create the experiment
echo "Creating Beaker GRPO experiment..."
$PYTHON /tmp/run_grpo_experiment.py \
    "$IMAGE_TAG" \
    "$BEAKER_USER" \
    "$GIT_BRANCH" \
    "$GIT_HASH" \
    "$PREEMPTIBLE" \
    "$EXP_NAME" \
    "${PYTHON_ARGS[@]}"

# Clean up temporary file
rm /tmp/run_grpo_experiment.py

echo "GRPO training experiment submitted successfully!"