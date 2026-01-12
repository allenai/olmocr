#!/bin/bash

# Runs an olmocr-bench run using the full pipeline (no fallback) for infrapartner testing
#
# Just make a beaker secret in the ai2/olmocr workspace with your API key
#
# Testing parasail
# scripts/run_infrapartner_benchmark.sh --server https://api.parasail.io/v1 --model allenai/olmOCR-2-7B-1025 --beaker-secret jakep-parasail-api-key 
#
# Testing deepinfra
# scripts/run_infrapartner_benchmark.sh --server https://api.deepinfra.com/v1/openai --model allenai/olmOCR-2-7B-1025 --beaker-secret jakep-deepinfra-api-key
#
# Testing Cirrascale
# scripts/run_infrapartner_benchmark.sh --server https://ai2endpoints.cirrascale.ai/api --model allenai/olmOCR-2-7B-1025 --beaker-secret jakep-cirrascale-api-key
set -e

# Parse command line arguments
MODEL=""
SERVER=""
BEAKER_SECRET=""
BENCH_BRANCH=""
BEAKER_IMAGE=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --model)
            MODEL="$2"
            shift 2
            ;;
        --server)
            SERVER="$2"
            shift 2
            ;;
        --beaker-secret)
            BEAKER_SECRET="$2"
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
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--server SERVER_URL] [--model MODEL_NAME] [--beaker-secret SECRET_NAME] [--benchbranch BRANCH_NAME] [--beaker-image IMAGE_NAME]"
            exit 1
            ;;
    esac
done

# # Check for uncommitted changes
# if [ -n "$BEAKER_IMAGE" ]; then
#  echo "Skipping docker build"
# else
#     if ! git diff-index --quiet HEAD --; then
#         echo "Error: There are uncommitted changes in the repository."
#         echo "Please commit or stash your changes before running the benchmark."
#         echo ""
#         echo "Uncommitted changes:"
#         git status --short
#         exit 1
#     fi
# fi

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
cat << 'EOF' > /tmp/run_infrapartner_benchmark_experiment.py
import sys
from beaker import Beaker, ExperimentSpec, TaskSpec, TaskContext, ResultSpec, TaskResources, ImageSource, Priority, Constraints, EnvVar

# Get image tag, beaker user, git branch, git hash, optional model, server, beaker_secret, and bench branch from command line
image_tag = sys.argv[1]
beaker_user = sys.argv[2]
git_branch = sys.argv[3]
git_hash = sys.argv[4]
model = None
server = None
beaker_secret = None
bench_branch = None

# Parse remaining arguments
arg_idx = 5
while arg_idx < len(sys.argv):
    if sys.argv[arg_idx] == "--benchbranch":
        bench_branch = sys.argv[arg_idx + 1]
        arg_idx += 2
    elif sys.argv[arg_idx] == "--model":
        model = sys.argv[arg_idx + 1]
        arg_idx += 2
    elif sys.argv[arg_idx] == "--server":
        server = sys.argv[arg_idx + 1]
        arg_idx += 2
    elif sys.argv[arg_idx] == "--beaker-secret":
        beaker_secret = sys.argv[arg_idx + 1]
        arg_idx += 2
    else:
        print(f"Unknown argument: {sys.argv[arg_idx]}")
        arg_idx += 1

# Initialize Beaker client
b = Beaker.from_env(default_workspace="ai2/olmocr")

# Build the pipeline command with optional parameters
pipeline_cmd = "python -m olmocr.pipeline ./localworkspace --markdown --pdfs ./olmOCR-bench/bench_data/pdfs/**/*.pdf --workers 1 --max_concurrent_requests 20"
if model:
    pipeline_cmd += f" --model {model}"
if server:
    pipeline_cmd += f" --server {server}"
if beaker_secret:
    pipeline_cmd += " --api_key \"$API_KEY\""

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

# If beaker_secret is provided, export it as API_KEY environment variable
if beaker_secret:
    commands.append('export API_KEY="$BEAKER_API_KEY"')

# Build git clone command with optional branch
git_clone_cmd = "git clone https://huggingface.co/datasets/allenai/olmOCR-bench"
if bench_branch:
    git_clone_cmd += f" -b {bench_branch}"

commands.extend([
    git_clone_cmd,
    "cd olmOCR-bench && git lfs pull && cd ..",
    pipeline_cmd,
    "python olmocr/bench/scripts/workspace_to_bench.py localworkspace/ olmOCR-bench/bench_data/olmocr --bench-path ./olmOCR-bench/",
    "pip install s5cmd",
    "s5cmd cp localworkspace/ s3://ai2-oe-data/jakep/olmocr-bench-runs/$BEAKER_WORKLOAD_ID/",
    "python -m olmocr.bench.benchmark --dir ./olmOCR-bench/bench_data"
])

# Build task spec with optional env vars
# If image_tag contains '/', it's already a full beaker image reference
if '/' in image_tag:
    image_ref = image_tag
else:
    image_ref = f"{beaker_user}/{image_tag}"

task_spec_args = {
    "name": "olmocr-infrapartner-benchmark",
    "image": ImageSource(beaker=image_ref),
    "command": [
        "bash", "-c",
        " && ".join(commands)
    ],
    "context": TaskContext(
        priority=Priority.normal,
        preemptible=True,
    ),
    "resources": TaskResources(gpu_count=0),
    "constraints": Constraints(cluster=["ai2/phobos", "ai2/neptune", "ai2/saturn"]),
    "result": ResultSpec(path="/noop-results"),
}

# Build env vars list
env_vars = []
if has_aws_creds:
    env_vars.append(EnvVar(name="AWS_CREDENTIALS_FILE", secret=aws_creds_secret))
if beaker_secret:
    env_vars.append(EnvVar(name="BEAKER_API_KEY", secret=beaker_secret))

# Add env vars if any exist
if env_vars:
    task_spec_args["env_vars"] = env_vars

# Create experiment spec
experiment_spec = ExperimentSpec(
    description=f"OlmOCR InfraPartner Benchmark Run - Branch: {git_branch}, Commit: {git_hash}",
    budget="ai2/oe-base",
    tasks=[TaskSpec(**task_spec_args)],
)

# Create the experiment
experiment = b.experiment.create(spec=experiment_spec, workspace="ai2/olmocr")
print(f"Created benchmark experiment: {experiment.id}")
print(f"View at: https://beaker.org/ex/{experiment.id}")
print("-------")
print("")
print("Note: Performance test has been skipped for infrapartner benchmark")
EOF

# Run the Python script to create the experiment
echo "Creating Beaker experiment..."

# Build command with appropriate arguments
CMD="$PYTHON /tmp/run_infrapartner_benchmark_experiment.py $IMAGE_TAG $BEAKER_USER $GIT_BRANCH $GIT_HASH"

if [ -n "$MODEL" ]; then
    echo "Using model: $MODEL"
    CMD="$CMD --model $MODEL"
fi

if [ -n "$SERVER" ]; then
    echo "Using server: $SERVER"
    CMD="$CMD --server $SERVER"
fi

if [ -n "$BEAKER_SECRET" ]; then
    echo "Using beaker secret for API key: $BEAKER_SECRET"
    CMD="$CMD --beaker-secret $BEAKER_SECRET"
fi

if [ -n "$BENCH_BRANCH" ]; then
    echo "Using bench branch: $BENCH_BRANCH"
    CMD="$CMD --benchbranch $BENCH_BRANCH"
fi

eval $CMD

# Clean up temporary file
rm /tmp/run_infrapartner_benchmark_experiment.py

echo "InfraPartner benchmark experiment submitted successfully!"