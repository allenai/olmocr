"""GCP job submission utilities using Managed Instance Groups."""
import logging
import os
import re
import subprocess
import sys
import time

logger = logging.getLogger(__name__)

# GPU type configurations for GCP
# "regions" list: first entry is the default, all entries used with --gcp-multiregion
# H100 regions from: gcloud compute accelerator-types list | grep nvidia-h100-80gb
# H200 regions from: gcloud compute accelerator-types list | grep nvidia-h200-141gb
GCP_GPU_CONFIGS = {
    "1xH100": {
        "machine_type": "a3-highgpu-1g",
        "accelerator_type": "nvidia-h100-80gb",
        "accelerator_count": 1,
        "regions": [
            "us-central1",
            "us-west1",
            "us-east4",
            "us-east5",
            "us-west4",
            "europe-west1",
            "europe-west2",
            "europe-west3",
            "europe-west4",
            "europe-west9",
            "europe-north1",
            "asia-east1",
            "asia-northeast1",
            "asia-northeast3",
            "asia-southeast1",
            "asia-south1",
            "asia-south2",
            "australia-southeast1",
            "northamerica-northeast2",
        ],
    },
    "8xH100": {
        "machine_type": "a3-highgpu-8g",
        "accelerator_type": "nvidia-h100-80gb",
        "accelerator_count": 8,
        "regions": [
            "us-central1",
            "us-west1",
            "us-east4",
            "us-east5",
            "us-west4",
            "europe-west1",
            "europe-west2",
            "europe-west3",
            "europe-west4",
            "europe-west9",
            "europe-north1",
            "asia-east1",
            "asia-northeast1",
            "asia-northeast3",
            "asia-southeast1",
            "asia-south1",
            "asia-south2",
            "australia-southeast1",
            "northamerica-northeast2",
        ],
    },
    "8xH200": {
        "machine_type": "a3-ultragpu-8g",
        "accelerator_type": "nvidia-h200-141gb",
        "accelerator_count": 8,
        "regions": [
            "us-west1",
            "us-central1",
            "us-east4",
            "us-east5",
            "us-south1",
            "europe-west1",
            "europe-west4",
            "asia-south1",
            "asia-south2",
        ],
    },
}

# GitHub repo for olmocr
OLMOCR_REPO = "https://github.com/allenai/olmocr.git"


def add_gcp_args(parser):
    """Add GCP-specific arguments to the parser."""
    gcp_args = parser.add_argument_group("GCP Specific configuration")
    gcp_args.add_argument(
        "--gcp",
        action="store_true",
        help="Submit this job to GCP instead of running locally",
    )
    gcp_args.add_argument(
        "--gcp-project",
        type=str,
        default="ai2-allennlp",
        help="GCP project ID",
    )
    gcp_args.add_argument(
        "--gcp-instances",
        type=int,
        default=1,
        help="Number of instances to create in the managed instance group",
    )
    gcp_args.add_argument(
        "--gcp-gpu-type",
        type=str,
        choices=list(GCP_GPU_CONFIGS.keys()),
        default="1xH100",
        help="GPU configuration: 1xH100, 8xH100, or 8xH200",
    )
    gcp_args.add_argument(
        "--gcp-multiregion",
        type=int,
        default=1,
        help="Number of regions to launch MIGs in (increases chances of getting capacity). Incompatible with --gcp-region.",
    )
    gcp_args.add_argument(
        "--gcp-region",
        type=str,
        default=None,
        help="Force a specific GCP region (e.g. us-west1). Incompatible with --gcp-multiregion.",
    )
    gcp_args.add_argument(
        "--gcp-aws-credentials",
        action="store_true",
        help="Mount ~/.aws/credentials on GCP instances via Secret Manager",
    )
    return gcp_args


def get_git_info():
    """Get current git branch and commit hash."""
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, check=True
        ).stdout.strip()

        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True
        ).stdout.strip()

        return branch, commit
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to get git info: {e}")
        sys.exit(1)


def submit_gcp_job(args, unknown_args):
    """Submit a job to GCP using a Managed Instance Group."""
    # Use latest docker image (without version suffix for dev work)
    docker_image = "alleninstituteforai/olmocr:latest"

    # Get current git branch and commit
    git_branch, git_commit = get_git_info()
    logger.info(f"Using git branch: {git_branch}, commit: {git_commit}")


    # Get GPU config
    gpu_config = GCP_GPU_CONFIGS[args.gcp_gpu_type]
    all_regions = gpu_config["regions"]

    # Determine which regions to use
    if args.gcp_region and args.gcp_multiregion > 1:
        logger.error("--gcp-region and --gcp-multiregion are mutually exclusive")
        sys.exit(1)

    if args.gcp_region:
        if args.gcp_region not in all_regions:
            logger.error(
                f"Region '{args.gcp_region}' is not available for {args.gcp_gpu_type}. "
                f"Available regions: {', '.join(all_regions)}"
            )
            sys.exit(1)
        regions_to_use = [args.gcp_region]
    else:
        num_regions = min(args.gcp_multiregion, len(all_regions))
        regions_to_use = all_regions[:num_regions]

    # Generate unique names based on workspace and GCP user
    gcp_account = subprocess.run(
        ["gcloud", "config", "get-value", "account"],
        capture_output=True, text=True
    ).stdout.strip()
    # Extract username from email (before @)
    username = gcp_account.split("@")[0] if "@" in gcp_account else "unknown"
    workspace_name = os.path.basename(args.workspace.rstrip("/"))
    timestamp = int(time.time())

    # Sanitize names for GCP (only lowercase letters, numbers, and hyphens allowed)
    def sanitize_gcp_name(name):
        # Replace underscores and other invalid chars with hyphens, lowercase
        sanitized = re.sub(r'[^a-z0-9-]', '-', name.lower())
        # Remove consecutive hyphens
        sanitized = re.sub(r'-+', '-', sanitized)
        # Remove leading/trailing hyphens
        sanitized = sanitized.strip('-')
        return sanitized

    sanitized_username = sanitize_gcp_name(username)
    sanitized_workspace = sanitize_gcp_name(workspace_name)

    # GCP names must be <= 63 chars and match regex '(?:[a-z](?:[-a-z0-9]{0,61}[a-z0-9])?)'
    # template_name format is "olmocr-{combined}-{timestamp}-{region}"
    # Longest region is "northamerica-northeast2" (23 chars)
    # "olmocr-" (7) + timestamp (~10) + 2 hyphens + region (23) = ~42 chars
    # So we have ~21 chars for username + workspace combined
    max_name_len = 63 - len("olmocr-") - len(str(timestamp)) - 25 - 3  # 3 for hyphens
    combined = f"{sanitized_username}-{sanitized_workspace}"
    if len(combined) > max_name_len:
        combined = combined[:max_name_len].rstrip('-')

    base_name = f"olmocr-{combined}-{timestamp}"

    # Create AWS credentials secret if requested
    aws_secret_name = None
    if getattr(args, 'gcp_aws_credentials', False):
        aws_creds_path = os.path.expanduser("~/.aws/credentials")
        if not os.path.exists(aws_creds_path):
            logger.error("~/.aws/credentials not found")
            sys.exit(1)

        aws_secret_name = f"{base_name}-aws-creds"

        # Create secret in Secret Manager
        logger.info(f"Creating AWS credentials secret: {aws_secret_name}")
        result = subprocess.run([
            "gcloud", "secrets", "create", aws_secret_name,
            f"--project={args.gcp_project}",
            "--replication-policy=automatic",
        ], capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"Failed to create secret: {result.stderr}")
            sys.exit(1)

        # Add version with credentials content
        result = subprocess.run([
            "gcloud", "secrets", "versions", "add", aws_secret_name,
            f"--project={args.gcp_project}",
            f"--data-file={aws_creds_path}",
        ], capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"Failed to add secret version: {result.stderr}")
            sys.exit(1)

        # Grant default compute service account access to the secret
        project_number = subprocess.run([
            "gcloud", "projects", "describe", args.gcp_project,
            "--format=value(projectNumber)",
        ], capture_output=True, text=True).stdout.strip()

        compute_sa = f"{project_number}-compute@developer.gserviceaccount.com"
        result = subprocess.run([
            "gcloud", "secrets", "add-iam-policy-binding", aws_secret_name,
            f"--project={args.gcp_project}",
            f"--member=serviceAccount:{compute_sa}",
            "--role=roles/secretmanager.secretAccessor",
        ], capture_output=True, text=True)
        if result.returncode != 0:
            logger.warning(f"Failed to grant secret access (may already exist): {result.stderr}")

        logger.info(f"AWS credentials secret created and configured")

    # Build the pipeline command arguments
    # Remove --gcp flags AND their values since workers will run locally
    args_list = []
    skip_next = False
    for arg in sys.argv[1:]:
        if skip_next:
            skip_next = False
            continue
        if arg.startswith("--gcp"):
            if arg in ("--gcp", "--gcp-aws-credentials"):
                # store_true flags, no value to skip
                continue
            elif "=" in arg:
                # --gcp-foo=value format, just skip this arg
                continue
            else:
                # --gcp-foo value format, skip this arg and the next one
                skip_next = True
                continue
        args_list.append(arg)
    # Also remove --pdfs since queue is populated by the submitter
    args_list = [
        arg
        for i, arg in enumerate(args_list)
        if not (
            arg.startswith("--pdfs") or (i > 0 and args_list[i - 1] == "--pdfs")
        )
    ]

    pipeline_cmd = " ".join(["python", "-m", "olmocr.pipeline"] + args_list)
    if unknown_args:
        pipeline_cmd += " " + " ".join(unknown_args)

    # Generate startup script that uses Docker with mounted code from git
    startup_script = f'''#!/bin/bash
set -euo pipefail

LOG_FILE="/var/log/olmocr-startup.log"
exec > >(tee -a "${{LOG_FILE}}") 2>&1

echo "$(date): Starting olmocr setup..."

# Configuration from metadata
DOCKER_IMAGE="{docker_image}"
GIT_REPO="{OLMOCR_REPO}"
GIT_BRANCH=$(curl -s "http://metadata.google.internal/computeMetadata/v1/instance/attributes/GIT_BRANCH" -H "Metadata-Flavor: Google")
GIT_COMMIT=$(curl -s "http://metadata.google.internal/computeMetadata/v1/instance/attributes/GIT_COMMIT" -H "Metadata-Flavor: Google")

echo "$(date): Git branch: $GIT_BRANCH, commit: $GIT_COMMIT"

# Wait for GPU to be available
echo "$(date): Waiting for GPU..."
for i in {{1..30}}; do
    if nvidia-smi &>/dev/null; then
        echo "$(date): GPU detected"
        nvidia-smi
        break
    fi
    echo "$(date): Waiting for GPU... attempt ${{i}}/30"
    sleep 10
done

# Install Docker if not present
if ! command -v docker &> /dev/null; then
    echo "$(date): Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl start docker
    systemctl enable docker
fi

# Install NVIDIA Container Toolkit if not present
if ! dpkg -l | grep -q nvidia-container-toolkit; then
    echo "$(date): Installing NVIDIA Container Toolkit..."
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --batch --yes --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \\
        sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \\
        tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
    apt-get update
    apt-get install -y nvidia-container-toolkit
    nvidia-ctk runtime configure --runtime=docker
    systemctl restart docker
fi

# Clone the olmocr repo and checkout the specific commit
echo "$(date): Cloning olmocr repo..."
OLMOCR_DIR="/opt/olmocr-source"
rm -rf "$OLMOCR_DIR"
git clone --branch "$GIT_BRANCH" "$GIT_REPO" "$OLMOCR_DIR"
cd "$OLMOCR_DIR"
git checkout "$GIT_COMMIT"
echo "$(date): Checked out commit $(git rev-parse HEAD)"

# Pull the Docker image
echo "$(date): Pulling Docker image ${{DOCKER_IMAGE}}..."
docker pull "${{DOCKER_IMAGE}}"

# Fetch AWS credentials from Secret Manager if configured
AWS_MOUNT=""
AWS_SECRET_NAME=$(curl -s "http://metadata.google.internal/computeMetadata/v1/instance/attributes/AWS_SECRET_NAME" -H "Metadata-Flavor: Google" 2>/dev/null || echo "")
AWS_PROJECT=$(curl -s "http://metadata.google.internal/computeMetadata/v1/instance/attributes/PROJECT" -H "Metadata-Flavor: Google" 2>/dev/null || echo "")
if [ -n "$AWS_SECRET_NAME" ] && [ "$AWS_SECRET_NAME" != "" ]; then
    echo "$(date): Fetching AWS credentials from Secret Manager..."
    mkdir -p /root/.aws
    gcloud secrets versions access latest --secret="$AWS_SECRET_NAME" --project="$AWS_PROJECT" > /root/.aws/credentials
    chmod 600 /root/.aws/credentials
    AWS_MOUNT="-v /root/.aws:/root/.aws:ro"
    echo "$(date): AWS credentials installed"
fi

# Run the pipeline in Docker with mounted source code
# Mount the cloned repo over /app/olmocr to override the baked-in code
echo "$(date): Starting pipeline in Docker..."
echo "$(date): Command: {pipeline_cmd}"
set +e
docker run --rm --gpus all \\
    -e GOOGLE_APPLICATION_CREDENTIALS=/root/.config/gcloud/application_default_credentials.json \\
    -v /root/.config/gcloud:/root/.config/gcloud:ro \\
    $AWS_MOUNT \\
    -v "$OLMOCR_DIR:/build" \\
    "${{DOCKER_IMAGE}}" \\
    -c "{pipeline_cmd}"
PIPELINE_EXIT_CODE=$?
set -e

echo "$(date): Pipeline finished with exit code $PIPELINE_EXIT_CODE"

# Get instance metadata for cleanup
INSTANCE_NAME=$(curl -s "http://metadata.google.internal/computeMetadata/v1/instance/name" -H "Metadata-Flavor: Google")
MIG_NAME=$(curl -s "http://metadata.google.internal/computeMetadata/v1/instance/attributes/MIG_NAME" -H "Metadata-Flavor: Google")
REGION=$(curl -s "http://metadata.google.internal/computeMetadata/v1/instance/attributes/REGION" -H "Metadata-Flavor: Google")
PROJECT=$(curl -s "http://metadata.google.internal/computeMetadata/v1/instance/attributes/PROJECT" -H "Metadata-Flavor: Google")

if [ $PIPELINE_EXIT_CODE -eq 0 ]; then
    # Success - remove instance from MIG (won't be replaced)
    echo "$(date): Pipeline completed successfully, removing instance from MIG..."

    # Check if we're the last instance before deleting ourselves
    MIG_SIZE=$(gcloud compute instance-groups managed describe "$MIG_NAME" \\
        --region="$REGION" \\
        --project="$PROJECT" \\
        --format="value(targetSize)" 2>/dev/null || echo "0")

    TEMPLATE_NAME=$(gcloud compute instance-groups managed describe "$MIG_NAME" \\
        --region="$REGION" \\
        --project="$PROJECT" \\
        --format="value(instanceTemplate)" 2>/dev/null | xargs basename || echo "")

    echo "$(date): Current MIG size: $MIG_SIZE"

    # Delete ourselves from the MIG (regional MIG uses --region)
    gcloud compute instance-groups managed delete-instances "$MIG_NAME" \\
        --instances="$INSTANCE_NAME" \\
        --region="$REGION" \\
        --project="$PROJECT" \\
        --quiet || echo "$(date): Failed to delete instance (may already be deleted)"

    # If we were the last instance, clean up MIG and template
    if [ "$MIG_SIZE" -eq 1 ]; then
        echo "$(date): Last instance - cleaning up MIG and template..."

        # Wait for our deletion to complete
        sleep 30

        # Delete the MIG
        gcloud compute instance-groups managed delete "$MIG_NAME" \\
            --region="$REGION" \\
            --project="$PROJECT" \\
            --quiet || echo "$(date): Failed to delete MIG"

        # Delete the instance template
        if [ -n "$TEMPLATE_NAME" ]; then
            gcloud compute instance-templates delete "$TEMPLATE_NAME" \\
                --project="$PROJECT" \\
                --quiet || echo "$(date): Failed to delete template"
        fi

        echo "$(date): Cleanup complete"
    else
        echo "$(date): Instance deletion requested, $((MIG_SIZE - 1)) instances remaining"
    fi
else
    # Error - shutdown and let MIG create a replacement to retry
    echo "$(date): Pipeline failed with exit code $PIPELINE_EXIT_CODE, shutting down for retry..."
    shutdown -h now
fi
'''

    # Write startup script to a temp file
    startup_script_path = f"/tmp/startup_script_{timestamp}.sh"
    with open(startup_script_path, "w") as f:
        f.write(startup_script)

    # Track created resources for output
    created_migs = []

    # Create template and MIG for each region
    for region in regions_to_use:
        template_name = f"{base_name}-{region}"
        mig_name = f"{base_name}-mig-{region}"

        # Create instance template with git info in metadata
        logger.info(f"Creating instance template: {template_name}")

        metadata = f"MIG_NAME={mig_name},REGION={region},PROJECT={args.gcp_project},GIT_BRANCH={git_branch},GIT_COMMIT={git_commit}"
        if aws_secret_name:
            metadata += f",AWS_SECRET_NAME={aws_secret_name}"

        # Use cloud-platform scope when Secret Manager access is needed, otherwise use specific scopes
        scopes = "cloud-platform" if aws_secret_name else "storage-rw,logging-write,compute-rw"

        template_cmd = [
            "gcloud", "compute", "instance-templates", "create", template_name,
            f"--project={args.gcp_project}",
            f"--machine-type={gpu_config['machine_type']}",
            f"--accelerator=count={gpu_config['accelerator_count']},type={gpu_config['accelerator_type']}",
            "--image-family=common-cu128-ubuntu-2204-nvidia-570",
            "--image-project=deeplearning-platform-release",
            "--boot-disk-size=64GB",
            f"--scopes={scopes}",
            f"--metadata={metadata}",
            f"--metadata-from-file=startup-script={startup_script_path}",
            "--provisioning-model=SPOT",
            "--maintenance-policy=TERMINATE",
        ]

        result = subprocess.run(template_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"Failed to create instance template for {region}: {result.stderr}")
            continue  # Try next region instead of failing completely
        logger.info(f"Instance template created successfully for {region}")

        # Create regional Managed Instance Group with ANY distribution shape
        logger.info(f"Creating regional managed instance group: {mig_name} with {args.gcp_instances} instances")
        mig_cmd = [
            "gcloud", "compute", "instance-groups", "managed", "create", mig_name,
            f"--project={args.gcp_project}",
            f"--template={template_name}",
            f"--size={args.gcp_instances}",
            f"--region={region}",
            "--target-distribution-shape=any",
        ]

        result = subprocess.run(mig_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"Failed to create MIG for {region}: {result.stderr}")
            # Clean up the template we just created
            subprocess.run([
                "gcloud", "compute", "instance-templates", "delete", template_name,
                f"--project={args.gcp_project}", "--quiet"
            ], capture_output=True)
            continue  # Try next region

        created_migs.append({
            "template": template_name,
            "mig": mig_name,
            "region": region,
        })

    # Clean up startup script
    os.unlink(startup_script_path)

    if not created_migs:
        logger.error("Failed to create MIGs in any region")
        sys.exit(1)

    print(f"\nGCP Job submitted successfully!")
    print(f"  Regions: {len(created_migs)}/{len(regions_to_use)} requested")
    print(f"  Instances per region: {args.gcp_instances}")
    print(f"  GPU Type: {args.gcp_gpu_type}")
    print(f"  Docker Image: {docker_image}")
    print(f"  Git Branch: {git_branch}")
    print(f"  Git Commit: {git_commit}")
    print(f"  Distribution Shape: ANY")
    print(f"\nCreated MIGs:")
    for mig_info in created_migs:
        print(f"  - {mig_info['region']}: {mig_info['mig']}")
    print(f"\nAuto-cleanup: Instances self-delete when done. Last instance deletes MIG and template.")
    print(f"\nTo monitor instances:")
    for mig_info in created_migs:
        print(f"  gcloud compute instance-groups managed list-instances {mig_info['mig']} --region={mig_info['region']} --project={args.gcp_project}")
    print(f"\nTo view logs on an instance:")
    print(f"  gcloud compute ssh <instance-name> --zone=<zone> --project={args.gcp_project} --command='tail -f /var/log/olmocr-startup.log'")
    print(f"\nManual cleanup (if needed):")
    for mig_info in created_migs:
        print(f"  gcloud compute instance-groups managed delete {mig_info['mig']} --region={mig_info['region']} --project={args.gcp_project} --quiet")
        print(f"  gcloud compute instance-templates delete {mig_info['template']} --project={args.gcp_project} --quiet")
