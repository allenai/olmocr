"""Beaker job submission utilities."""
import logging
import os
import sys

import boto3

logger = logging.getLogger(__name__)


def add_beaker_args(parser):
    """Add beaker-specific arguments to the parser."""
    beaker_group = parser.add_argument_group("beaker/cluster execution")
    beaker_group.add_argument("--beaker", action="store_true", help="Submit this job to beaker instead of running locally")
    beaker_group.add_argument("--beaker_workspace", help="Beaker workspace to submit to", default="ai2/olmocr")
    beaker_group.add_argument(
        "--beaker_cluster",
        help="Beaker clusters you want to run on",
        default=["ai2/jupiter", "ai2/ceres", "ai2/neptune", "ai2/saturn"],
    )
    beaker_group.add_argument("--beaker_gpus", type=int, default=1, help="Number of gpu replicas to run")
    beaker_group.add_argument("--beaker_priority", type=str, default="normal", help="Beaker priority level for the job")
    return beaker_group


async def setup_beaker_environment():
    """
    Set up the beaker environment if running inside a beaker job.
    Returns True if running in beaker, False otherwise.
    """
    import asyncio
    import random

    if "BEAKER_JOB_NAME" not in os.environ:
        return False

    cred_path = os.path.join(os.path.expanduser("~"), ".aws", "credentials")
    os.makedirs(os.path.dirname(cred_path), exist_ok=True)
    with open(cred_path, "w") as f:
        f.write(os.environ.get("AWS_CREDENTIALS_FILE", ""))

    cred_path = os.path.join(os.path.expanduser("~"), ".gcs", "credentials")
    os.makedirs(os.path.dirname(cred_path), exist_ok=True)
    with open(cred_path, "w") as f:
        f.write(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_FILE", ""))
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = cred_path

    # Wait a little bit so that not all beaker jobs in a task start at the same time and download the model at the same time
    replica_count = int(os.environ.get("BEAKER_REPLICA_COUNT", "1"))
    interval = 10 if (replica_count - 1) * 10 <= 30 else 30 / max(1, replica_count - 1)
    sleep_time = int(os.environ.get("BEAKER_REPLICA_RANK", "0")) * interval
    logger.info(f"Beaker job sleeping for {sleep_time} seconds to stagger model downloads")
    await asyncio.sleep(sleep_time)

    return True


def submit_beaker_job(args):
    """Submit a job to Beaker."""
    from beaker import (  # type: ignore
        Beaker,
        BeakerConstraints,
        BeakerEnvVar,
        BeakerExperimentSpec,
        BeakerImageSource,
        BeakerJobPriority,
        BeakerResultSpec,
        BeakerRetrySpec,
        BeakerTaskContext,
        BeakerTaskResources,
        BeakerTaskSpec,
    )
    from beaker.exceptions import BeakerSecretNotFound

    from olmocr.version import VERSION

    Beaker.TIMEOUT = 60
    b = Beaker.from_env(default_workspace=args.beaker_workspace)
    owner = b.user_name
    beaker_image = f"jakep/olmocr-inference-{VERSION}"

    task_name = f"olmocr-{os.path.basename(args.workspace.rstrip('/'))}"

    # Take out --beaker flag so the workers will just run things
    args_list = [arg for arg in sys.argv[1:] if arg != "--beaker"]

    # Take out the --pdfs [arg] or --pdfs=[arg], since the queue is populated locally
    args_list = [arg for i, arg in enumerate(args_list) if not (arg.startswith("--pdfs") or (i > 0 and args_list[i - 1] == "--pdfs"))]

    try:
        b.secret.get(f"{owner}-WEKA_ACCESS_KEY_ID")
        b.secret.get(f"{owner}-WEKA_SECRET_ACCESS_KEY")
        b.secret.get(f"{owner}-AWS_CREDENTIALS_FILE")
    except BeakerSecretNotFound:
        print(
            f"Expected beaker secrets for accessing Weka and S3 are not found. Are you okay to write those to your beaker workspace {args.beaker_workspace}? [y/n]"
        )

        if input().strip().lower() != "y":
            print("Exiting...")
            sys.exit(1)

        b.secret.write(f"{owner}-WEKA_ACCESS_KEY_ID", os.environ.get("WEKA_ACCESS_KEY_ID", ""))
        b.secret.write(f"{owner}-WEKA_SECRET_ACCESS_KEY", os.environ.get("WEKA_SECRET_ACCESS_KEY", ""))
        b.secret.write(
            f"{owner}-AWS_CREDENTIALS_FILE",
            open(os.path.join(os.path.expanduser("~"), ".aws", "credentials")).read(),
        )

    env_var_secrets = [
        BeakerEnvVar(name="WEKA_ACCESS_KEY_ID", secret=f"{owner}-WEKA_ACCESS_KEY_ID"),
        BeakerEnvVar(name="WEKA_SECRET_ACCESS_KEY", secret=f"{owner}-WEKA_SECRET_ACCESS_KEY"),
        BeakerEnvVar(name="AWS_CREDENTIALS_FILE", secret=f"{owner}-AWS_CREDENTIALS_FILE"),
    ]

    try:
        b.secret.get("OLMOCR_PREVIEW_HF_TOKEN")
        env_var_secrets.append(BeakerEnvVar(name="HF_TOKEN", secret="OLMOCR_PREVIEW_HF_TOKEN"))
    except BeakerSecretNotFound:
        pass

    try:
        b.secret.get("OE_DATA_GCS_SA_KEY")
        env_var_secrets.append(BeakerEnvVar(name="GOOGLE_APPLICATION_CREDENTIALS_FILE", secret="OE_DATA_GCS_SA_KEY"))
    except BeakerSecretNotFound:
        print("Input the olmo-gcs SA key if you would like to load weights from gcs (end with a double newline):")
        lines = []
        prev_empty = False
        for line in iter(input, None):
            if not line and prev_empty:
                break
            prev_empty = not line
            lines.append(line)
        gcs_sa_key = "\n".join(lines[:-1]).strip()  # Remove the last empty line
        if gcs_sa_key:
            b.secret.write("OE_DATA_GCS_SA_KEY", gcs_sa_key)
            env_var_secrets.append(BeakerEnvVar(name="GOOGLE_APPLICATION_CREDENTIALS_FILE", secret="OE_DATA_GCS_SA_KEY"))

    # Create the experiment spec
    experiment_spec = BeakerExperimentSpec(
        budget="ai2/oe-base",
        description=task_name,
        tasks=[
            BeakerTaskSpec(
                name=task_name,
                propagate_failure=False,
                propagate_preemption=False,
                replicas=args.beaker_gpus,
                context=BeakerTaskContext(
                    priority=BeakerJobPriority[args.beaker_priority],
                    preemptible=True,
                ),
                image=BeakerImageSource(beaker=beaker_image),
                command=["python", "-m", "olmocr.pipeline"] + args_list,
                env_vars=[
                    BeakerEnvVar(name="BEAKER_JOB_NAME", value=task_name),
                    BeakerEnvVar(name="OWNER", value=owner),
                    BeakerEnvVar(name="HF_HUB_OFFLINE", value="1"),
                ]
                + env_var_secrets,
                resources=BeakerTaskResources(gpu_count=1, memory="125GB"),  # Have to set a memory limit, otherwise VLLM may use too much on its own
                constraints=BeakerConstraints(cluster=args.beaker_cluster if isinstance(args.beaker_cluster, list) else [args.beaker_cluster]),
                result=BeakerResultSpec(path="/noop-results"),
            )
        ],
        retry=BeakerRetrySpec(allowed_task_retries=10),
    )

    workload = b.experiment.create(spec=experiment_spec)

    print(f"Experiment URL: https://beaker.org/ex/{workload.experiment.id}")
