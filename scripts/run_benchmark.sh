#!/bin/bash

# Runs an olmocr-bench run using the full pipeline (no fallback)
#  Without model parameter (default behavior): uses the default image from hugging face
#   ./scripts/run_benchmark.sh
#  With model parameter: for testing custom models
#   ./scripts/run_benchmark.sh --model your-model-name
#  With cluster parameter: specify a specific cluster to use
#   ./scripts/run_benchmark.sh --cluster ai2/titan-cirrascale
#  With beaker image: skip Docker build and use provided Beaker image
#   ./scripts/run_benchmark.sh --beaker-image jakep/olmocr-benchmark-0.3.3-780bc7d934
#  With repeats parameter: run the pipeline multiple times for increased accuracy (default: 1)
#   ./scripts/run_benchmark.sh --repeats 3

set -e

# Parse command line arguments
MODEL=""
CLUSTER=""
BENCH_BRANCH=""
BEAKER_IMAGE=""
REPEATS="1"
while [[ $# -gt 0 ]]; do
    case $1 in
        --model)
            MODEL="$2"
            shift 2
            ;;
        --cluster)
            CLUSTER="$2"
            shift 2
            ;;
        --benchbranch)
            BENCH_BRANCH="$2"
            shift 2
            ;;
        --beaker-image)
            BEAKER_IMAGE="$2"
            shift 2
            ;;
        --repeats)
            REPEATS="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--model MODEL_NAME] [--cluster CLUSTER_NAME] [--benchbranch BRANCH_NAME] [--beaker-image IMAGE_NAME] [--repeats NUMBER]"
            exit 1
            ;;
    esac
done

# Check for uncommitted changes
if [ -n "$BEAKER_IMAGE" ]; then
 echo "Skipping docker build"
else
    if ! git diff-index --quiet HEAD --; then
        echo "Error: There are uncommitted changes in the repository."
        echo "Please commit or stash your changes before running the benchmark."
        echo ""
        echo "Uncommitted changes:"
        git status --short
        exit 1
    fi
fi

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

# Check if a Beaker image was provided
if [ -n "$BEAKER_IMAGE" ]; then
    echo "Using provided Beaker image: $BEAKER_IMAGE"
    IMAGE_TAG="$BEAKER_IMAGE"
else
    # Create full image tag
    IMAGE_TAG="olmocr-benchmark-${VERSION}-${GIT_HASH}"
    echo "Building Docker image with tag: $IMAGE_TAG"

    # Build the Docker image
    echo "Building Docker image..."
    docker build --platform linux/amd64 -f ./Dockerfile -t $IMAGE_TAG .

    # Push image to beaker
    echo "Trying to push image to Beaker..."
    if ! beaker image create --workspace ai2/oe-data-pdf --name $IMAGE_TAG $IMAGE_TAG 2>/dev/null; then
        echo "Warning: Beaker image with tag $IMAGE_TAG already exists. Using existing image."
    fi
fi

# Get Beaker username
BEAKER_USER=$(beaker account whoami --format json | jq -r '.[0].name')
echo "Beaker user: $BEAKER_USER"

# Create Python script to run beaker experiment
cat << 'EOF' > /tmp/run_benchmark_experiment.py
import sys
from beaker import Beaker, ExperimentSpec, TaskSpec, TaskContext, ResultSpec, TaskResources, ImageSource, Priority, Constraints, EnvVar

# Get image tag, beaker user, git branch, git hash, optional model, cluster, bench branch, and repeats from command line
image_tag = sys.argv[1]
beaker_user = sys.argv[2]
git_branch = sys.argv[3]
git_hash = sys.argv[4]
model = None
cluster = None
bench_branch = None
repeats = 1

# Parse remaining arguments
arg_idx = 5
while arg_idx < len(sys.argv):
    if sys.argv[arg_idx] == "--cluster":
        cluster = sys.argv[arg_idx + 1]
        arg_idx += 2
    elif sys.argv[arg_idx] == "--benchbranch":
        bench_branch = sys.argv[arg_idx + 1]
        arg_idx += 2
    elif sys.argv[arg_idx] == "--repeats":
        repeats = int(sys.argv[arg_idx + 1])
        arg_idx += 2
    else:
        model = sys.argv[arg_idx]
        arg_idx += 1

# Initialize Beaker client
b = Beaker.from_env(default_workspace="ai2/olmocr")

# Note: pipeline commands will be built in the loop based on repeats

# Check if AWS credentials secret exists
aws_creds_secret = f"{beaker_user}-AWS_CREDENTIALS_FILE"
try:
    # Try to get the secret to see if it exists
    b.secret.get(aws_creds_secret, workspace="ai2/olmocr")
    has_aws_creds = True
    print(f"Found AWS credentials secret: {aws_creds_secret}")
except:
    has_aws_creds = False
    print(f"AWS credentials secret not found: {aws_creds_secret}")

# First experiment: Original benchmark job
commands = []
if has_aws_creds:
    commands.extend([
        "mkdir -p ~/.aws",
        'echo "$AWS_CREDENTIALS_FILE" > ~/.aws/credentials'
    ])

# Build git clone command with optional branch
git_clone_cmd = "git clone https://huggingface.co/datasets/allenai/olmOCR-bench"
if bench_branch:
    git_clone_cmd += f" -b {bench_branch}"

commands.extend([
    git_clone_cmd,
    "cd olmOCR-bench && git lfs pull && cd ..",
])

# Run pipeline multiple times based on repeats
for i in range(1, repeats + 1):
    workspace_dir = f"./localworkspace{i}"
    pipeline_cmd = f"python -m olmocr.pipeline {workspace_dir} --markdown --pdfs ./olmOCR-bench/bench_data/pdfs/**/*.pdf"
    if model:
        pipeline_cmd += f" --model {model}"
    commands.append(pipeline_cmd)

# Process all workspaces with workspace_to_bench.py
for i in range(1, repeats + 1):
    workspace_dir = f"localworkspace{i}/"
    workspace_to_bench_cmd = f"python olmocr/bench/scripts/workspace_to_bench.py {workspace_dir} olmOCR-bench/bench_data/olmocr --bench-path ./olmOCR-bench/ --repeat-index {i}"
    commands.append(workspace_to_bench_cmd)

# Copy all workspaces to S3 and run benchmark
commands.extend([
    "pip install s5cmd",
])

# Copy each workspace to S3
for i in range(1, repeats + 1):
    workspace_dir = f"localworkspace{i}/"
    commands.append(f"s5cmd cp {workspace_dir} s3://ai2-oe-data/jakep/olmocr-bench-runs/$BEAKER_WORKLOAD_ID/workspace{i}/")

commands.append("python -m olmocr.bench.benchmark --dir ./olmOCR-bench/bench_data")

# Build task spec with optional env vars
# If image_tag contains '/', it's already a full beaker image reference
if '/' in image_tag:
    image_ref = image_tag
else:
    image_ref = f"{beaker_user}/{image_tag}"

task_spec_args = {
    "name": "olmocr-benchmark",
    "image": ImageSource(beaker=image_ref),
    "command": [
        "bash", "-c",
        " && ".join(commands)
    ],
    "context": TaskContext(
        priority=Priority.normal,
        preemptible=True,
    ),
    "resources": TaskResources(gpu_count=1),
    "constraints": Constraints(cluster=[cluster] if cluster else ["ai2/ceres-cirrascale", "ai2/jupiter-cirrascale-2"]),
    "result": ResultSpec(path="/noop-results"),
}

# Add env vars if AWS credentials exist
if has_aws_creds:
    task_spec_args["env_vars"] = [
        EnvVar(name="AWS_CREDENTIALS_FILE", secret=aws_creds_secret)
    ]

# Create first experiment spec
experiment_spec = ExperimentSpec(
    description=f"OlmOCR Benchmark Run - Branch: {git_branch}, Commit: {git_hash}",
    budget="ai2/oe-base",
    tasks=[TaskSpec(**task_spec_args)],
)

# Create the first experiment
experiment = b.experiment.create(spec=experiment_spec, workspace="ai2/olmocr")
print(f"Created benchmark experiment: {experiment.id}")
print(f"View at: https://beaker.org/ex/{experiment.id}")
print("-------")
print("")

# Second experiment: Performance test job
perf_pipeline_cmd = "python -m olmocr.pipeline ./localworkspace1 --markdown --pdfs s3://ai2-oe-data/jakep/olmocr/olmOCR-mix-0225/benchmark_set/*.pdf"
if model:
    perf_pipeline_cmd += f" --model {model}"

perf_commands = []
if has_aws_creds:
    perf_commands.extend([
        "mkdir -p ~/.aws",
        'echo "$AWS_CREDENTIALS_FILE" > ~/.aws/credentials'
    ])
perf_commands.append(perf_pipeline_cmd)

# Build performance task spec
perf_task_spec_args = {
    "name": "olmocr-performance",
    "image": ImageSource(beaker=image_ref),
    "command": [
        "bash", "-c",
        " && ".join(perf_commands)
    ],
    "context": TaskContext(
        priority=Priority.normal,
        preemptible=True,
    ),
    # Need to reserve all 8 gpus for performance spec or else benchmark results can be off (1 for titan-cirrascale)
    "resources": TaskResources(gpu_count=1 if cluster == "ai2/titan-cirrascale" else 8),
    "constraints": Constraints(cluster=[cluster] if cluster else ["ai2/ceres-cirrascale", "ai2/jupiter-cirrascale-2"]),
    "result": ResultSpec(path="/noop-results"),
}

# Add env vars if AWS credentials exist
if has_aws_creds:
    perf_task_spec_args["env_vars"] = [
        EnvVar(name="AWS_CREDENTIALS_FILE", secret=aws_creds_secret)
    ]

# Create performance experiment spec
perf_experiment_spec = ExperimentSpec(
    description=f"OlmOCR Performance Test - Branch: {git_branch}, Commit: {git_hash}",
    budget="ai2/oe-base",
    tasks=[TaskSpec(**perf_task_spec_args)],
)

# Create the performance experiment
perf_experiment = b.experiment.create(spec=perf_experiment_spec, workspace="ai2/olmocr")
print(f"Created performance experiment: {perf_experiment.id}")
print(f"View at: https://beaker.org/ex/{perf_experiment.id}")
EOF

# Run the Python script to create the experiments
echo "Creating Beaker experiments..."

# Build command with appropriate arguments
CMD="$PYTHON /tmp/run_benchmark_experiment.py $IMAGE_TAG $BEAKER_USER $GIT_BRANCH $GIT_HASH"

if [ -n "$MODEL" ]; then
    echo "Using model: $MODEL"
    CMD="$CMD $MODEL"
fi

if [ -n "$CLUSTER" ]; then
    echo "Using cluster: $CLUSTER"
    CMD="$CMD --cluster $CLUSTER"
fi

if [ -n "$BENCH_BRANCH" ]; then
    echo "Using bench branch: $BENCH_BRANCH"
    CMD="$CMD --benchbranch $BENCH_BRANCH"
fi

if [ "$REPEATS" != "1" ]; then
    echo "Using repeats: $REPEATS"
    CMD="$CMD --repeats $REPEATS"
fi

eval $CMD

# Clean up temporary file
rm /tmp/run_benchmark_experiment.py

echo "Benchmark experiments submitted successfully!"