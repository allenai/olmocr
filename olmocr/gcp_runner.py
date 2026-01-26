"""GCP job submission utilities using Managed Instance Groups."""
import logging
import os
import re
import subprocess
import sys
import time

logger = logging.getLogger(__name__)

# GPU type configurations for GCP
GCP_GPU_CONFIGS = {
    "1xH100": {
        "machine_type": "a3-highgpu-1g",
        "accelerator_type": "nvidia-h100-80gb",
        "accelerator_count": 1,
        "region": "us-central1",
    },
    "8xH100": {
        "machine_type": "a3-highgpu-8g",
        "accelerator_type": "nvidia-h100-80gb",
        "accelerator_count": 8,
        "region": "us-central1",
    },
    "8xH200": {
        "machine_type": "a3-ultragpu-8g",
        "accelerator_type": "nvidia-h200-141gb",
        "accelerator_count": 8,
        "region": "us-west1",
    },
}


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
        default="8xH100",
        help="GPU configuration: 1xH100, 8xH100, or 8xH200",
    )
    return gcp_args


def submit_gcp_job(args, unknown_args):
    """Submit a job to GCP using a Managed Instance Group."""
    from olmocr.version import VERSION

    # Validate workspace is GCS
    if not args.workspace.startswith("gs://"):
        logger.error("GCP jobs require a GCS workspace (gs://...)")
        sys.exit(1)

    # Get GPU config
    gpu_config = GCP_GPU_CONFIGS[args.gcp_gpu_type]
    region = gpu_config["region"]

    # Docker image to use
    docker_image = f"alleninstituteforai/olmocr:v{VERSION}-with-model"

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
    # template_name prefix is "olmocr-" (7 chars) + timestamp (~10 chars) + 2 hyphens = ~19 chars
    # So we have ~44 chars for username + workspace combined
    max_name_len = 63 - len("olmocr-") - len(str(timestamp)) - 2  # 2 for the hyphens
    combined = f"{sanitized_username}-{sanitized_workspace}"
    if len(combined) > max_name_len:
        combined = combined[:max_name_len].rstrip('-')

    template_name = f"olmocr-{combined}-{timestamp}"
    mig_name = f"olmocr-mig-{combined}-{timestamp}"

    # Build the pipeline command arguments
    # Remove --gcp flags AND their values since workers will run locally
    args_list = []
    skip_next = False
    for arg in sys.argv[1:]:
        if skip_next:
            skip_next = False
            continue
        if arg.startswith("--gcp"):
            if arg == "--gcp":
                # --gcp is a store_true flag, no value to skip
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

    # Generate startup script that uses Docker
    startup_script = f'''#!/bin/bash
set -euo pipefail

LOG_FILE="/var/log/olmocr-startup.log"
exec > >(tee -a "${{LOG_FILE}}") 2>&1

echo "$(date): Starting olmocr setup..."

# Configuration
DOCKER_IMAGE="{docker_image}"

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

# Pull the Docker image
echo "$(date): Pulling Docker image ${{DOCKER_IMAGE}}..."
docker pull "${{DOCKER_IMAGE}}"

# Run the pipeline in Docker (disable set -e to capture exit code)
echo "$(date): Starting pipeline in Docker..."
set +e
docker run --rm --gpus all \\
    -e GOOGLE_APPLICATION_CREDENTIALS=/root/.config/gcloud/application_default_credentials.json \\
    -v /root/.config/gcloud:/root/.config/gcloud:ro \\
    "${{DOCKER_IMAGE}}" \\
    {pipeline_cmd}
PIPELINE_EXIT_CODE=$?
set -e

# Get instance metadata
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

    # Create instance template
    logger.info(f"Creating instance template: {template_name}")
    logger.info(f"Using Docker image: {docker_image}")
    template_cmd = [
        "gcloud", "compute", "instance-templates", "create", template_name,
        f"--project={args.gcp_project}",
        f"--machine-type={gpu_config['machine_type']}",
        f"--accelerator=count={gpu_config['accelerator_count']},type={gpu_config['accelerator_type']}",
        "--image-family=common-cu128-ubuntu-2204-nvidia-570",
        "--image-project=deeplearning-platform-release",
        "--boot-disk-size=2TB",
        "--scopes=storage-rw,logging-write,compute-rw",
        f"--metadata=MIG_NAME={mig_name},REGION={region},PROJECT={args.gcp_project}",
        f"--metadata-from-file=startup-script={startup_script_path}",
        "--provisioning-model=SPOT",
        "--maintenance-policy=TERMINATE",
    ]

    result = subprocess.run(template_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"Failed to create instance template: {result.stderr}")
        sys.exit(1)
    logger.info("Instance template created successfully")

    # Clean up startup script
    os.unlink(startup_script_path)

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
        logger.error(f"Failed to create MIG: {result.stderr}")
        sys.exit(1)

    print(f"\nGCP Job submitted successfully!")
    print(f"  Template: {template_name}")
    print(f"  MIG: {mig_name}")
    print(f"  Region: {region}")
    print(f"  Instances: {args.gcp_instances}")
    print(f"  GPU Type: {args.gcp_gpu_type}")
    print(f"  Docker Image: {docker_image}")
    print(f"  Distribution Shape: ANY")
    print(f"\nAuto-cleanup: Instances self-delete when done. Last instance deletes MIG and template.")
    print(f"\nTo monitor instances:")
    print(f"  gcloud compute instance-groups managed list-instances {mig_name} --region={region} --project={args.gcp_project}")
    print(f"\nTo view logs on an instance:")
    print(f"  gcloud compute ssh <instance-name> --zone=<zone> --project={args.gcp_project} --command='tail -f /var/log/olmocr-startup.log'")
    print(f"\nManual cleanup (if needed):")
    print(f"  gcloud compute instance-groups managed delete {mig_name} --region={region} --project={args.gcp_project} --quiet")
    print(f"  gcloud compute instance-templates delete {template_name} --project={args.gcp_project} --quiet")
