import abc
import asyncio
import datetime
import hashlib
import logging
import os
import random
from asyncio import Queue
from dataclasses import dataclass
from typing import Any, List, Optional
import json

from olmocr.s3_utils import (
    download_zstd_csv,
    expand_s3_glob,
    parse_s3_path,
    upload_zstd_csv,
)

logger = logging.getLogger(__name__)


@dataclass
class WorkItem:
    """Represents a single work item in the queue"""

    hash: str
    work_paths: List[str]


class WorkQueue(abc.ABC):
    """
    Base class defining the interface for a work queue.
    """

    @abc.abstractmethod
    async def populate_queue(self, work_paths: List[str], items_per_group: int) -> None:
        """
        Add new items to the work queue. The specifics will vary depending on
        whether this is a local or S3-backed queue.

        Args:
            work_paths: Each individual path that we will process over
            items_per_group: Number of items to group together in a single work item
        """
        pass

    @abc.abstractmethod
    async def initialize_queue(self) -> int:
        """
        Load the work queue from the relevant store (local or remote)
        and initialize it for processing.

        For example, this might remove already completed work items and randomize
        the order before adding them to an internal queue.
        """
        pass

    @abc.abstractmethod
    async def is_completed(self, work_hash: str) -> bool:
        """
        Check if a work item has been completed.

        Args:
            work_hash: Hash of the work item to check

        Returns:
            True if the work is completed, False otherwise
        """
        pass

    @abc.abstractmethod
    async def get_work(self, worker_lock_timeout_secs: int = 1800) -> Optional[WorkItem]:
        """
        Get the next available work item that isn't completed or locked.

        Args:
            worker_lock_timeout_secs: Number of seconds before considering
                                      a worker lock stale (default 30 mins)

        Returns:
            WorkItem if work is available, None if queue is empty
        """
        pass

    @abc.abstractmethod
    async def mark_done(self, work_item: WorkItem) -> None:
        """
        Mark a work item as done by removing its lock file
        or performing any other cleanup.

        Args:
            work_item: The WorkItem to mark as done
        """
        pass

    @property
    @abc.abstractmethod
    def size(self) -> int:
        """Get current size of work queue"""
        pass

    @staticmethod
    def _compute_workgroup_hash(work_paths: List[str]) -> str:
        """
        Compute a deterministic hash for a group of paths.

        Args:
            work_paths: List of paths (local or S3)

        Returns:
            SHA1 hash of the sorted paths
        """
        sha1 = hashlib.sha1()
        for path in sorted(work_paths):
            sha1.update(path.encode("utf-8"))
        return sha1.hexdigest()


# --------------------------------------------------------------------------------------
# Local Helpers for reading/writing the index CSV (compressed with zstd) to disk
# --------------------------------------------------------------------------------------

try:
    import zstandard
except ImportError:
    zstandard = None


def download_zstd_csv_local(local_path: str) -> List[str]:
    """
    Download a zstd-compressed CSV from a local path.
    If the file doesn't exist, returns an empty list.
    """
    if not os.path.exists(local_path):
        return []

    if not zstandard:
        raise RuntimeError("zstandard package is required for local zstd CSV operations.")

    with open(local_path, "rb") as f:
        dctx = zstandard.ZstdDecompressor()
        data = dctx.decompress(f.read())
    lines = data.decode("utf-8").splitlines()
    return lines


def upload_zstd_csv_local(local_path: str, lines: List[str]) -> None:
    """
    Upload a zstd-compressed CSV to a local path.
    """
    if not zstandard:
        raise RuntimeError("zstandard package is required for local zstd CSV operations.")

    data = "\n".join(lines).encode("utf-8")
    cctx = zstandard.ZstdCompressor()
    compressed_data = cctx.compress(data)

    # Ensure parent directories exist
    os.makedirs(os.path.dirname(local_path), exist_ok=True)

    with open(local_path, "wb") as f:
        f.write(compressed_data)


# --------------------------------------------------------------------------------------
# LocalWorkQueue Implementation
# --------------------------------------------------------------------------------------


class LocalWorkQueue(WorkQueue):
    """
    A local in-memory and on-disk WorkQueue implementation, which uses
    a local workspace directory to store the queue index, lock files,
    and completed results for persistent resumption across process restarts.
    """

    def __init__(self, workspace_path: str):
        """
        Initialize the local work queue.

        Args:
            workspace_path: Local directory path where the queue index,
                            results, and locks are stored.
        """
        self.workspace_path = os.path.abspath(workspace_path)
        os.makedirs(self.workspace_path, exist_ok=True)

        # Local index file (compressed)
        self._index_path = os.path.join(self.workspace_path, "work_index_list.csv.zstd")

        # Output directory for completed tasks
        self._results_dir = os.path.join(self.workspace_path, "results")
        os.makedirs(self._results_dir, exist_ok=True)

        # Directory for lock files
        self._locks_dir = os.path.join(self.workspace_path, "worker_locks")
        os.makedirs(self._locks_dir, exist_ok=True)

        # Internal queue
        self._queue: Queue[Any] = Queue()

    async def populate_queue(self, work_paths: List[str], items_per_group: int) -> None:
        """
        Add new items to the work queue (local version).

        Args:
            work_paths: Each individual path (local in this context)
                           that we will process over
            items_per_group: Number of items to group together in a single work item
        """
        # Treat them as local paths, but keep variable name for consistency
        all_paths = set(work_paths)
        logger.info(f"Found {len(all_paths):,} total paths")

        # Load existing work groups from local index
        existing_lines = await asyncio.to_thread(download_zstd_csv_local, self._index_path)
        existing_groups = {}
        for line in existing_lines:
            if line.strip():
                parts = line.strip().split(",")
                group_hash = parts[0]
                group_paths = parts[1:]
                existing_groups[group_hash] = group_paths

        existing_path_set = {p for paths in existing_groups.values() for p in paths}
        new_paths = all_paths - existing_path_set
        logger.info(f"{len(new_paths):,} new paths to add to the workspace")

        if not new_paths:
            return

        # Create new work groups
        new_groups = []
        current_group = []
        for path in sorted(new_paths):
            current_group.append(path)
            if len(current_group) == items_per_group:
                group_hash = self._compute_workgroup_hash(current_group)
                new_groups.append((group_hash, current_group))
                current_group = []
        if current_group:
            group_hash = self._compute_workgroup_hash(current_group)
            new_groups.append((group_hash, current_group))

        logger.info(f"Created {len(new_groups):,} new work groups")

        # Combine and save updated work groups
        combined_groups = existing_groups.copy()
        for group_hash, group_paths in new_groups:
            combined_groups[group_hash] = group_paths

        combined_lines = [",".join([group_hash] + group_paths) for group_hash, group_paths in combined_groups.items()]

        if new_groups:
            # Write the combined data back to disk in zstd CSV format
            await asyncio.to_thread(upload_zstd_csv_local, self._index_path, combined_lines)

    async def initialize_queue(self) -> int:
        """
        Load the work queue from the local index file and initialize it for processing.
        Removes already completed work items and randomizes the order.
        """
        # 1) Read the index
        work_queue_lines = await asyncio.to_thread(download_zstd_csv_local, self._index_path)
        work_queue = {parts[0]: parts[1:] for line in work_queue_lines if (parts := line.strip().split(",")) and line.strip()}

        # 2) Determine which items are completed by scanning and loading local results/*.jsonl
        if not os.path.isdir(self._results_dir):
            os.makedirs(self._results_dir, exist_ok=True)
        existing_work_items = [f for f in os.listdir(self._results_dir) if f.startswith("output_") and f.endswith(".jsonl")]
        done_work_items = []
        for item in existing_work_items:
            item_hash = item[len("output_"):-len(".jsonl")]
            item_path = os.path.join(self._results_dir, item)
            lock_file_path = os.path.join(self._locks_dir, item)
            done_work_paths = []
            try:
                with open(item_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        try:
                            result = json.loads(line)
                            done_pdf_orig_path = result.get('metadata', {}).get('Source-File')
                            if done_pdf_orig_path:
                                done_work_paths.append(done_pdf_orig_path)
                            elif logger.isEnabledFor(logging.DEBUG):
                                logger.debug(f"{item} did not contain any output (parsed) content")
                        except json.JSONDecodeError as e:
                            print(f"Error parsing line in {item}: {e}")
                        except Exception as e:
                            logger.warning(f"Error processing result: {e}")
            except Exception as e:
                print(f"Error opening {item}: {e}")
                continue       
            # Check if work is complete
            if set(work_queue.get(item_hash)) == set(done_work_paths):
                done_work_items.append(item)
            else:
                missing = set(work_queue.get(item_hash)) - set(done_work_paths)
                logger.info(f"Work item with hash {item_hash} is not fully finished, re-running PDFs: {', '.join(missing)}")
                try:
                    os.remove(item_path)
                    logger.info(f"Deleted output file: {item_path}")
                except Exception as e:
                    logger.warning(f"Error deleting {item_path}: {e}")
                try:
                    if os.path.exists(lock_file_path):
                        os.remove(lock_file_path)
                        logger.info(f"Deleted lock file: {lock_file_path}")
                    else:
                        logger.info(f"Lock file {lock_file_path} does not exist, skipping deletion")
                except Exception as e:
                    logger.warning(f"Error deleting lock file {lock_file_path}: {e}")
                #TODO: check if pipeline writes output dolma_docs in mode 'w/w+' (overwrite) or 'a' (append)
                # If it is 'a', we need to remove the corresponding path in work_queue to avoid repeating work
                # work_queue[item_hash] = [path for path in missing if path not in done_work_paths]
                    
        # done_work_items = [f for f in os.listdir(self._results_dir) if f.startswith("output_") and f.endswith(".jsonl")]
        done_work_hashes = {fn[len("output_") : -len(".jsonl")] for fn in done_work_items}

        # 3) Filter out completed items
        remaining_work_hashes = set(work_queue) - done_work_hashes
        remaining_items = [WorkItem(hash=hash_, work_paths=work_queue[hash_]) for hash_ in remaining_work_hashes]
        random.shuffle(remaining_items)

        # 4) Initialize our in-memory queue
        self._queue = asyncio.Queue()
        for item in remaining_items:
            await self._queue.put(item)

        logger.info(f"Initialized local queue with {self._queue.qsize()} work items")

        return self._queue.qsize()

    async def is_completed(self, work_hash: str) -> bool:
        """
        Check if a work item has been completed locally by seeing if
        output_{work_hash}.jsonl is present in the results directory.

        Args:
            work_hash: Hash of the work item to check
        """
        output_file = os.path.join(self._results_dir, f"output_{work_hash}.jsonl")
        return os.path.exists(output_file)

    async def get_work(self, worker_lock_timeout_secs: int = 1800) -> Optional[WorkItem]:
        """
        Get the next available work item that isn't completed or locked.

        Args:
            worker_lock_timeout_secs: Number of seconds before considering
                                      a worker lock stale (default 30 mins)

        Returns:
            WorkItem if work is available, None if queue is empty
        """
        while True:
            try:
                work_item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return None

            # Check if work is already completed
            if await self.is_completed(work_item.hash):
                logger.debug(f"Work item {work_item.hash} already completed, skipping")
                self._queue.task_done()
                continue

            # Check for worker lock
            lock_file = os.path.join(self._locks_dir, f"output_{work_item.hash}.jsonl")
            if os.path.exists(lock_file):
                # Check modification time
                mtime = datetime.datetime.fromtimestamp(os.path.getmtime(lock_file), datetime.timezone.utc)
                if (datetime.datetime.now(datetime.timezone.utc) - mtime).total_seconds() > worker_lock_timeout_secs:
                    # Lock is stale, we can take this work
                    logger.debug(f"Found stale lock for {work_item.hash}, taking work item")
                else:
                    # Lock is active, skip this work
                    logger.debug(f"Work item {work_item.hash} is locked by another worker, skipping")
                    self._queue.task_done()
                    continue

            # Create our lock file (touch an empty file)
            try:
                with open(lock_file, "wb") as f:
                    f.write(b"")
            except Exception as e:
                logger.warning(f"Failed to create lock file for {work_item.hash}: {e}")
                self._queue.task_done()
                continue

            return work_item

    async def mark_done(self, work_item: WorkItem) -> None:
        """
        Mark a work item as done by removing its lock file.

        Args:
            work_item: The WorkItem to mark as done
        """
        lock_file = os.path.join(self._locks_dir, f"output_{work_item.hash}.jsonl")
        if os.path.exists(lock_file):
            try:
                os.remove(lock_file)
            except Exception as e:
                logger.warning(f"Failed to delete lock file for {work_item.hash}: {e}")
        self._queue.task_done()

    @property
    def size(self) -> int:
        """Get current size of local work queue"""
        return self._queue.qsize()


# --------------------------------------------------------------------------------------
# S3WorkQueue Implementation
# --------------------------------------------------------------------------------------


class S3WorkQueue(WorkQueue):
    """
    Manages a work queue stored in S3 that coordinates work across multiple workers.
    The queue maintains a list of work items, where each work item is a group of s3 paths
    that should be processed together.

    Each work item gets a hash, and completed work items will have their results
    stored in s3://workspace_path/results/output_[hash].jsonl

    This is the ground source of truth about which work items are done.

    When a worker takes an item off the queue, it will write an empty s3 file to
    s3://workspace_path/worker_locks/output_[hash].jsonl

    The queue gets randomized on each worker, so workers pull random work items to operate on.
    As you pull an item, we will check to see if it has been completed. If yes,
    then it will immediately fetch the next item. If a lock file was created within a configurable
    timeout (30 mins by default), then that work item is also skipped.

    The lock will will be deleted once the worker is done with that item.
    """

    def __init__(self, s3_client, workspace_path: str):
        """
        Initialize the work queue.

        Args:
            s3_client: Boto3 S3 client to use for operations
            workspace_path: S3 path where work queue and results are stored
        """
        self.s3_client = s3_client
        self.workspace_path = workspace_path.rstrip("/")

        self._index_path = os.path.join(self.workspace_path, "work_index_list.csv.zstd")
        self._output_glob = os.path.join(self.workspace_path, "results", "*.jsonl")
        self._queue: Queue[Any] = Queue()

    async def populate_queue(self, work_paths: List[str], items_per_group: int) -> None:
        """
        Add new items to the work queue.

        Args:
            work_paths: Each individual s3 path that we will process over
            items_per_group: Number of items to group together in a single work item
        """
        all_paths = set(work_paths)
        logger.info(f"Found {len(all_paths):,} total paths")

        # Load existing work groups
        existing_lines = await asyncio.to_thread(download_zstd_csv, self.s3_client, self._index_path)
        existing_groups = {}
        for line in existing_lines:
            if line.strip():
                parts = line.strip().split(",")
                group_hash = parts[0]
                group_paths = parts[1:]
                existing_groups[group_hash] = group_paths

        existing_path_set = {path for paths in existing_groups.values() for path in paths}

        # Find new paths to process
        new_paths = all_paths - existing_path_set
        logger.info(f"{len(new_paths):,} new paths to add to the workspace")

        if not new_paths:
            return

        # Create new work groups
        new_groups = []
        current_group = []
        for path in sorted(new_paths):
            current_group.append(path)
            if len(current_group) == items_per_group:
                group_hash = self._compute_workgroup_hash(current_group)
                new_groups.append((group_hash, current_group))
                current_group = []
        if current_group:
            group_hash = self._compute_workgroup_hash(current_group)
            new_groups.append((group_hash, current_group))

        logger.info(f"Created {len(new_groups):,} new work groups")

        # Combine and save updated work groups
        combined_groups = existing_groups.copy()
        for group_hash, group_paths in new_groups:
            combined_groups[group_hash] = group_paths

        combined_lines = [",".join([group_hash] + group_paths) for group_hash, group_paths in combined_groups.items()]

        if new_groups:
            await asyncio.to_thread(upload_zstd_csv, self.s3_client, self._index_path, combined_lines)

    async def initialize_queue(self) -> int:
        """
        Load the work queue from S3 and initialize it for processing.
        Removes already completed work items and randomizes the order.
        """
        # Load work items and completed items in parallel
        download_task = asyncio.to_thread(download_zstd_csv, self.s3_client, self._index_path)
        expand_task = asyncio.to_thread(expand_s3_glob, self.s3_client, self._output_glob)

        work_queue_lines, done_work_items = await asyncio.gather(download_task, expand_task)

        # Process work queue lines
        work_queue = {parts[0]: parts[1:] for line in work_queue_lines if (parts := line.strip().split(",")) and line.strip()}

        # Get set of completed work hashes
        done_work_hashes = {
            os.path.basename(item)[len("output_") : -len(".jsonl")]
            for item in done_work_items
            if os.path.basename(item).startswith("output_") and os.path.basename(item).endswith(".jsonl")
        }

        # Find remaining work and shuffle
        remaining_work_hashes = set(work_queue) - done_work_hashes
        remaining_items = [WorkItem(hash=hash_, work_paths=work_queue[hash_]) for hash_ in remaining_work_hashes]
        random.shuffle(remaining_items)

        # Initialize queue
        self._queue = asyncio.Queue()
        for item in remaining_items:
            await self._queue.put(item)

        logger.info(f"Initialized queue with {self._queue.qsize()} work items")

        return self._queue.qsize()

    async def is_completed(self, work_hash: str) -> bool:
        """
        Check if a work item has been completed.

        Args:
            work_hash: Hash of the work item to check

        Returns:
            True if the work is completed, False otherwise
        """
        output_s3_path = os.path.join(self.workspace_path, "results", f"output_{work_hash}.jsonl")
        bucket, key = parse_s3_path(output_s3_path)

        try:
            await asyncio.to_thread(self.s3_client.head_object, Bucket=bucket, Key=key)
            return True
        except self.s3_client.exceptions.ClientError:
            return False

    async def get_work(self, worker_lock_timeout_secs: int = 1800) -> Optional[WorkItem]:
        """
        Get the next available work item that isn't completed or locked.

        Args:
            worker_lock_timeout_secs: Number of seconds before considering a worker lock stale (default 30 mins)

        Returns:
            WorkItem if work is available, None if queue is empty
        """
        while True:
            try:
                work_item = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return None

            # Check if work is already completed
            if await self.is_completed(work_item.hash):
                logger.debug(f"Work item {work_item.hash} already completed, skipping")
                self._queue.task_done()
                continue

            # Check for worker lock
            lock_path = os.path.join(self.workspace_path, "worker_locks", f"output_{work_item.hash}.jsonl")
            bucket, key = parse_s3_path(lock_path)

            try:
                response = await asyncio.to_thread(self.s3_client.head_object, Bucket=bucket, Key=key)

                # Check if lock is stale
                last_modified = response["LastModified"]
                if (datetime.datetime.now(datetime.timezone.utc) - last_modified).total_seconds() > worker_lock_timeout_secs:
                    # Lock is stale, we can take this work
                    logger.debug(f"Found stale lock for {work_item.hash}, taking work item")
                else:
                    # Lock is active, skip this work
                    logger.debug(f"Work item {work_item.hash} is locked by another worker, skipping")
                    self._queue.task_done()
                    continue

            except self.s3_client.exceptions.ClientError:
                # No lock exists, we can take this work
                pass

            # Create our lock file
            try:
                await asyncio.to_thread(self.s3_client.put_object, Bucket=bucket, Key=key, Body=b"")
            except Exception as e:
                logger.warning(f"Failed to create lock file for {work_item.hash}: {e}")
                self._queue.task_done()
                continue

            return work_item

    async def mark_done(self, work_item: WorkItem) -> None:
        """
        Mark a work item as done by removing its lock file.

        Args:
            work_item: The WorkItem to mark as done
        """
        lock_path = os.path.join(self.workspace_path, "worker_locks", f"output_{work_item.hash}.jsonl")
        bucket, key = parse_s3_path(lock_path)

        try:
            await asyncio.to_thread(self.s3_client.delete_object, Bucket=bucket, Key=key)
        except Exception as e:
            logger.warning(f"Failed to delete lock file for {work_item.hash}: {e}")

        self._queue.task_done()

    @property
    def size(self) -> int:
        """Get current size of work queue"""
        return self._queue.qsize()