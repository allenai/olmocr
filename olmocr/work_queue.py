import abc
import asyncio
import csv
import datetime
import hashlib
import io
import logging
import os
import random
from asyncio import Queue, QueueEmpty
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

import zstandard

from olmocr.cloud_utils import (
    download_zstd_csv,
    download_zstd_csv_gcs,
    expand_gcs_glob,
    expand_s3_glob,
    parse_s3_path,
    upload_zstd_csv,
    upload_zstd_csv_gcs,
)

logger = logging.getLogger(__name__)

# Shared directory names for both local and S3 backends
WORKER_LOCKS_DIR = "worker_locks"
DONE_FLAGS_DIR = "done_flags"


@dataclass
class WorkItem:
    """Represents a single work item in the queue."""

    hash: str
    work_paths: List[str]


class Backend(abc.ABC):
    """Abstract backend for storage operations."""

    @abc.abstractmethod
    async def load_index_lines(self) -> List[str]:
        """Load raw index lines from storage."""
        pass

    @abc.abstractmethod
    async def save_index_lines(self, lines: List[str]) -> None:
        """Save raw index lines to storage."""
        pass

    @abc.abstractmethod
    async def get_completed_hashes(self) -> Set[str]:
        """Get set of completed work hashes."""
        pass

    @abc.abstractmethod
    async def is_completed(self, work_hash: str) -> bool:
        """Check if a work item has been completed."""
        pass

    @abc.abstractmethod
    async def is_worker_lock_taken(self, work_hash: str, worker_lock_timeout_secs: int = 1800) -> bool:
        """Check if a worker lock is taken and not stale."""
        pass

    @abc.abstractmethod
    async def create_worker_lock(self, work_hash: str) -> None:
        """Create a worker lock for a work hash."""
        pass

    @abc.abstractmethod
    async def delete_worker_lock(self, work_hash: str) -> None:
        """Delete the worker lock for a work hash if it exists."""
        pass

    @abc.abstractmethod
    async def create_done_flag(self, work_hash: str) -> None:
        """Create a done flag for a work hash."""
        pass


class WorkQueue:
    """
    Manages a work queue with pluggable storage backends (e.g., local or S3).
    """

    def __init__(self, backend: Backend):
        self.backend = backend
        self._queue: Queue[WorkItem] = Queue()
        self._completed_hash_cache = set()

    @staticmethod
    def _encode_csv_row(row: List[str]) -> str:
        """Encodes a row of data for CSV storage with proper escaping."""
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(row)
        return output.getvalue().strip()

    @staticmethod
    def _decode_csv_row(line: str) -> List[str]:
        """Decodes a CSV row with proper unescaping."""
        return next(csv.reader([line]))

    @staticmethod
    def _compute_workgroup_hash(work_paths: List[str]) -> str:
        """Compute a deterministic hash for a group of paths."""
        sha1 = hashlib.sha1()
        for path in sorted(work_paths):
            sha1.update(path.encode("utf-8"))
        return sha1.hexdigest()

    def _parse_index_lines(self, lines: List[str]) -> Dict[str, List[str]]:
        """Parse index lines into a dict of hash to paths."""
        result = {}
        for line in lines:
            if line.strip():
                parts = self._decode_csv_row(line)
                if parts:
                    result[parts[0]] = parts[1:]
        return result

    def _make_index_lines(self, groups: Dict[str, List[str]]) -> List[str]:
        """Create encoded lines from groups dict."""
        return [self._encode_csv_row([group_hash] + group_paths) for group_hash, group_paths in groups.items()]

    async def populate_queue(self, work_paths: List[str], items_per_group: int) -> None:
        """
        Add new items to the work queue.
        """
        all_paths = set(work_paths)

        lines = await self.backend.load_index_lines()
        existing_groups = self._parse_index_lines(lines)

        existing_path_set = {p for paths in existing_groups.values() for p in paths}
        new_paths = sorted(all_paths - existing_path_set)

        if not new_paths:
            return

        new_groups = []
        for i in range(0, len(new_paths), items_per_group):
            group = new_paths[i : i + items_per_group]
            group_hash = self._compute_workgroup_hash(group)
            new_groups.append((group_hash, group))

        combined_groups = {**existing_groups, **dict(new_groups)}
        combined_lines = self._make_index_lines(combined_groups)

        await self.backend.save_index_lines(combined_lines)

    async def initialize_queue(self) -> int:
        """
        Load the work queue and initialize it for processing.
        Removes already completed work items and randomizes the order.
        """
        lines = await self.backend.load_index_lines()
        work_queue = self._parse_index_lines(lines)

        done_hashes = await self.backend.get_completed_hashes()

        remaining_hashes = set(work_queue) - done_hashes
        remaining_items = [WorkItem(hash=h, work_paths=work_queue[h]) for h in remaining_hashes]
        random.shuffle(remaining_items)

        self._queue = Queue()
        for item in remaining_items:
            await self._queue.put(item)

        logger.info(f"Initialized queue with {self.size:,} work items")
        return self.size

    async def get_work(self, worker_lock_timeout_secs: int = 1800) -> Optional[WorkItem]:
        """
        Get the next available work item that isn't completed or locked.
        """
        REFRESH_COMPLETED_HASH_CACHE_MAX_ATTEMPTS = 3
        refresh_completed_hash_attempt = 0

        while True:
            try:
                work_item = self._queue.get_nowait()
            except QueueEmpty:
                return None

            if work_item.hash in self._completed_hash_cache or await self.backend.is_completed(work_item.hash):
                logger.debug(f"Work item {work_item.hash} already completed, skipping")
                self._queue.task_done()

                refresh_completed_hash_attempt += 1

                if refresh_completed_hash_attempt >= REFRESH_COMPLETED_HASH_CACHE_MAX_ATTEMPTS:
                    logger.info(f"More than {REFRESH_COMPLETED_HASH_CACHE_MAX_ATTEMPTS} queue items already done, refreshing local completed cache fully")
                    self._completed_hash_cache = await self.backend.get_completed_hashes()
                    refresh_completed_hash_attempt = 0

                continue

            if await self.backend.is_worker_lock_taken(work_item.hash, worker_lock_timeout_secs):
                logger.debug(f"Work item {work_item.hash} is locked by another worker, skipping")
                self._queue.task_done()
                continue

            # Create lock (overwrites if stale)
            try:
                await self.backend.create_worker_lock(work_item.hash)
            except Exception as e:
                logger.warning(f"Failed to create lock for {work_item.hash}: {e}")
                self._queue.task_done()
                continue

            refresh_completed_hash_attempt = 0
            return work_item

    async def mark_done(self, work_item: WorkItem) -> None:
        """
        Mark a work item as done by removing its lock file and creating a done flag.
        """
        # Create done flag in done_flags_dir
        await self.backend.create_done_flag(work_item.hash)

        # Remove the worker lock
        await self.backend.delete_worker_lock(work_item.hash)
        self._queue.task_done()

    @property
    def size(self) -> int:
        """Get current size of work queue."""
        return self._queue.qsize()


class LocalBackend(Backend):
    """Local file system backend."""

    # Default timeout for filesystem ops, not to block queue, in seconds
    DEFAULT_FS_TIMEOUT = 120

    def __init__(self, workspace_path: str):
        self.workspace_path = os.path.abspath(workspace_path)
        self._index_path = os.path.join(self.workspace_path, "work_index_list.csv.zstd")
        self._done_flags_dir = os.path.join(self.workspace_path, DONE_FLAGS_DIR)
        self._locks_dir = os.path.join(self.workspace_path, WORKER_LOCKS_DIR)

        os.makedirs(self.workspace_path, exist_ok=True)
        os.makedirs(self._done_flags_dir, exist_ok=True)
        os.makedirs(self._locks_dir, exist_ok=True)

    async def _run_with_timeout(self, func, *args, operation_name: str = "filesystem operation"):
        """Run a blocking function in a thread with timeout and logging."""
        logger.debug(f"LocalBackend: Starting {operation_name}")
        try:
            result = await asyncio.wait_for(asyncio.to_thread(func, *args), timeout=LocalBackend.DEFAULT_FS_TIMEOUT)
            logger.debug(f"LocalBackend: Completed {operation_name}")
            return result
        except asyncio.TimeoutError:
            logger.error(f"LocalBackend: TIMEOUT after {LocalBackend.DEFAULT_FS_TIMEOUT}s on {operation_name}")
            raise TimeoutError(f"Filesystem operation '{operation_name}' timed out after {LocalBackend.DEFAULT_FS_TIMEOUT} seconds")

    def _download_zstd_csv_local(self, local_path: str) -> List[str]:
        """
        Read a zstd-compressed CSV from a local path.
        If the file doesn't exist, returns an empty list.
        """
        if not os.path.exists(local_path):
            return []

        with open(local_path, "rb") as f:
            dctx = zstandard.ZstdDecompressor()
            data = dctx.decompress(f.read())
        lines = data.decode("utf-8").splitlines()
        return lines

    def _upload_zstd_csv_local(self, local_path: str, lines: List[str]) -> None:
        """
        Write a zstd-compressed CSV to a local path.
        """
        data = "\n".join(lines).encode("utf-8")
        cctx = zstandard.ZstdCompressor()
        compressed_data = cctx.compress(data)

        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(compressed_data)

    async def load_index_lines(self) -> List[str]:
        return await asyncio.to_thread(self._download_zstd_csv_local, self._index_path)

    async def save_index_lines(self, lines: List[str]) -> None:
        await asyncio.to_thread(self._upload_zstd_csv_local, self._index_path, lines)

    async def get_completed_hashes(self) -> Set[str]:
        def _list_completed() -> Set[str]:
            if not os.path.isdir(self._done_flags_dir):
                return set()
            return {f[len("done_") : -len(".flag")] for f in os.listdir(self._done_flags_dir) if f.startswith("done_") and f.endswith(".flag")}

        return await asyncio.to_thread(_list_completed)

    def _get_worker_lock_path(self, work_hash: str) -> str:
        """Internal method to get worker lock path."""
        return os.path.join(self._locks_dir, f"worker_{work_hash}.lock")

    def _get_done_flag_path(self, work_hash: str) -> str:
        """Internal method to get done flag path."""
        return os.path.join(self._done_flags_dir, f"done_{work_hash}.flag")

    async def _get_object_mtime(self, path: str) -> Optional[datetime.datetime]:
        """Internal method to get object mtime."""

        def _get_mtime() -> Optional[datetime.datetime]:
            if not os.path.exists(path):
                return None
            return datetime.datetime.fromtimestamp(os.path.getmtime(path), datetime.timezone.utc)

        return await self._run_with_timeout(_get_mtime, operation_name=f"get_mtime({path})")

    async def is_worker_lock_taken(self, work_hash: str, worker_lock_timeout_secs: int = 1800) -> bool:
        """Check if a worker lock is taken and not stale."""
        lock_path = self._get_worker_lock_path(work_hash)
        try:
            lock_mtime = await self._get_object_mtime(lock_path)
        except (TimeoutError, Exception) as e:
            # On timeout or error, return False to let this worker attempt the work
            logger.warning(f"is_worker_lock_taken({work_hash}) failed: {e}, returning False")
            return False

        if not lock_mtime:
            return False

        now = datetime.datetime.now(datetime.timezone.utc)
        return (now - lock_mtime).total_seconds() <= worker_lock_timeout_secs

    async def create_worker_lock(self, work_hash: str) -> None:
        """Create a worker lock for a work hash. Best-effort, does not fail on timeout."""
        lock_path = self._get_worker_lock_path(work_hash)

        def _create() -> None:
            with open(lock_path, "wb"):
                pass

        try:
            await self._run_with_timeout(_create, operation_name=f"create_worker_lock({work_hash})")
        except (TimeoutError, Exception) as e:
            # Best effort - if we can't create lock, still proceed (duplicate work is okay)
            logger.warning(f"create_worker_lock({work_hash}) failed: {e}, proceeding anyway")

    async def delete_worker_lock(self, work_hash: str) -> None:
        """Delete the worker lock for a work hash if it exists. Best-effort, does not fail on timeout."""
        lock_path = self._get_worker_lock_path(work_hash)

        def _delete() -> None:
            if os.path.exists(lock_path):
                os.remove(lock_path)

        try:
            await self._run_with_timeout(_delete, operation_name=f"delete_worker_lock({work_hash})")
        except (TimeoutError, Exception) as e:
            # Best effort - if we can't delete lock, just log and continue
            logger.warning(f"delete_worker_lock({work_hash}) failed: {e}, proceeding anyway")

    async def is_completed(self, work_hash: str) -> bool:
        """Check if a work item has been completed."""
        done_flag_path = self._get_done_flag_path(work_hash)
        try:
            return await self._get_object_mtime(done_flag_path) is not None
        except (TimeoutError, Exception) as e:
            # On timeout or error, return False to let worker attempt the work
            logger.warning(f"is_completed({work_hash}) failed: {e}, returning False")
            return False

    async def create_done_flag(self, work_hash: str) -> None:
        """Create a done flag for a work hash. Best-effort, does not fail on timeout."""
        done_flag_path = self._get_done_flag_path(work_hash)

        def _create() -> None:
            with open(done_flag_path, "wb"):
                pass

        try:
            await self._run_with_timeout(_create, operation_name=f"create_done_flag({work_hash})")
        except (TimeoutError, Exception) as e:
            # Best effort - work was done, just couldn't mark it. Log and continue.
            logger.warning(f"create_done_flag({work_hash}) failed: {e}, proceeding anyway")


class S3Backend(Backend):
    """S3 backend."""

    def __init__(self, s3_client: Any, workspace_path: str):
        self.s3_client = s3_client
        self.workspace_path = workspace_path.rstrip("/")
        self._index_path = os.path.join(self.workspace_path, "work_index_list.csv.zstd")
        self._output_glob = os.path.join(self.workspace_path, DONE_FLAGS_DIR, "*.flag")

    async def load_index_lines(self) -> List[str]:
        return await asyncio.to_thread(download_zstd_csv, self.s3_client, self._index_path)

    async def save_index_lines(self, lines: List[str]) -> None:
        await asyncio.to_thread(upload_zstd_csv, self.s3_client, self._index_path, lines)

    async def get_completed_hashes(self) -> Set[str]:
        def _list_completed() -> Set[str]:
            done_work_items = expand_s3_glob(self.s3_client, self._output_glob)
            return {
                os.path.basename(item)[len("done_") : -len(".flag")]
                for item in done_work_items
                if os.path.basename(item).startswith("done_") and os.path.basename(item).endswith(".flag")
            }

        return await asyncio.to_thread(_list_completed)

    def _get_worker_lock_path(self, work_hash: str) -> str:
        """Internal method to get worker lock path."""
        return os.path.join(self.workspace_path, WORKER_LOCKS_DIR, f"worker_{work_hash}.lock")

    def _get_done_flag_path(self, work_hash: str) -> str:
        """Internal method to get done flag path."""
        return os.path.join(self.workspace_path, DONE_FLAGS_DIR, f"done_{work_hash}.flag")

    async def _get_object_mtime(self, path: str) -> Optional[datetime.datetime]:
        """Internal method to get object mtime."""
        bucket, key = parse_s3_path(path)

        def _head_object() -> Optional[datetime.datetime]:
            try:
                response = self.s3_client.head_object(Bucket=bucket, Key=key)
                return response["LastModified"]
            except self.s3_client.exceptions.ClientError as e:
                if e.response["Error"]["Code"] == "404":
                    return None
                raise

        return await asyncio.to_thread(_head_object)

    async def is_worker_lock_taken(self, work_hash: str, worker_lock_timeout_secs: int = 1800) -> bool:
        """Check if a worker lock is taken and not stale."""
        lock_path = self._get_worker_lock_path(work_hash)
        lock_mtime = await self._get_object_mtime(lock_path)

        if not lock_mtime:
            return False

        now = datetime.datetime.now(datetime.timezone.utc)
        return (now - lock_mtime).total_seconds() <= worker_lock_timeout_secs

    async def create_worker_lock(self, work_hash: str) -> None:
        """Create a worker lock for a work hash."""
        lock_path = self._get_worker_lock_path(work_hash)
        bucket, key = parse_s3_path(lock_path)
        await asyncio.to_thread(self.s3_client.put_object, Bucket=bucket, Key=key, Body=b"")

    async def delete_worker_lock(self, work_hash: str) -> None:
        """Delete the worker lock for a work hash if it exists."""
        lock_path = self._get_worker_lock_path(work_hash)
        bucket, key = parse_s3_path(lock_path)
        await asyncio.to_thread(self.s3_client.delete_object, Bucket=bucket, Key=key)

    async def is_completed(self, work_hash: str) -> bool:
        """Check if a work item has been completed."""
        done_flag_path = self._get_done_flag_path(work_hash)
        return await self._get_object_mtime(done_flag_path) is not None

    async def create_done_flag(self, work_hash: str) -> None:
        """Create a done flag for a work hash."""
        done_flag_path = self._get_done_flag_path(work_hash)
        bucket, key = parse_s3_path(done_flag_path)
        await asyncio.to_thread(self.s3_client.put_object, Bucket=bucket, Key=key, Body=b"")


class GCSBackend(Backend):
    """Google Cloud Storage backend."""

    def __init__(self, gcs_client: Any, workspace_path: str):
        self.gcs_client = gcs_client
        self.workspace_path = workspace_path.rstrip("/")
        self._index_path = os.path.join(self.workspace_path, "work_index_list.csv.zstd")
        self._output_glob = os.path.join(self.workspace_path, DONE_FLAGS_DIR, "*.flag")

    async def load_index_lines(self) -> List[str]:
        return await asyncio.to_thread(download_zstd_csv_gcs, self.gcs_client, self._index_path)

    async def save_index_lines(self, lines: List[str]) -> None:
        await asyncio.to_thread(upload_zstd_csv_gcs, self.gcs_client, self._index_path, lines)

    async def get_completed_hashes(self) -> Set[str]:
        def _list_completed() -> Set[str]:
            done_work_items = expand_gcs_glob(self.gcs_client, self._output_glob)
            return {
                os.path.basename(item)[len("done_") : -len(".flag")]
                for item in done_work_items
                if os.path.basename(item).startswith("done_") and os.path.basename(item).endswith(".flag")
            }

        return await asyncio.to_thread(_list_completed)

    def _get_worker_lock_path(self, work_hash: str) -> str:
        """Internal method to get worker lock path."""
        return os.path.join(self.workspace_path, WORKER_LOCKS_DIR, f"worker_{work_hash}.lock")

    def _get_done_flag_path(self, work_hash: str) -> str:
        """Internal method to get done flag path."""
        return os.path.join(self.workspace_path, DONE_FLAGS_DIR, f"done_{work_hash}.flag")

    async def _get_object_mtime(self, path: str) -> Optional[datetime.datetime]:
        """Internal method to get object mtime."""
        bucket_name, key = parse_s3_path(path)

        def _get_blob_mtime() -> Optional[datetime.datetime]:
            bucket = self.gcs_client.bucket(bucket_name)
            blob = bucket.blob(key)
            if blob.exists():
                blob.reload()
                return blob.updated
            return None

        return await asyncio.to_thread(_get_blob_mtime)

    async def is_worker_lock_taken(self, work_hash: str, worker_lock_timeout_secs: int = 1800) -> bool:
        """Check if a worker lock is taken and not stale."""
        lock_path = self._get_worker_lock_path(work_hash)
        lock_mtime = await self._get_object_mtime(lock_path)

        if not lock_mtime:
            return False

        now = datetime.datetime.now(datetime.timezone.utc)
        return (now - lock_mtime).total_seconds() <= worker_lock_timeout_secs

    async def create_worker_lock(self, work_hash: str) -> None:
        """Create a worker lock for a work hash."""
        lock_path = self._get_worker_lock_path(work_hash)
        bucket_name, key = parse_s3_path(lock_path)

        def _create_lock():
            bucket = self.gcs_client.bucket(bucket_name)
            blob = bucket.blob(key)
            blob.upload_from_string(b"", content_type="application/octet-stream")

        await asyncio.to_thread(_create_lock)

    async def delete_worker_lock(self, work_hash: str) -> None:
        """Delete the worker lock for a work hash if it exists."""
        lock_path = self._get_worker_lock_path(work_hash)
        bucket_name, key = parse_s3_path(lock_path)

        def _delete_lock():
            bucket = self.gcs_client.bucket(bucket_name)
            blob = bucket.blob(key)
            if blob.exists():
                blob.delete()

        await asyncio.to_thread(_delete_lock)

    async def is_completed(self, work_hash: str) -> bool:
        """Check if a work item has been completed."""
        done_flag_path = self._get_done_flag_path(work_hash)
        return await self._get_object_mtime(done_flag_path) is not None

    async def create_done_flag(self, work_hash: str) -> None:
        """Create a done flag for a work hash."""
        done_flag_path = self._get_done_flag_path(work_hash)
        bucket_name, key = parse_s3_path(done_flag_path)

        def _create_flag():
            bucket = self.gcs_client.bucket(bucket_name)
            blob = bucket.blob(key)
            blob.upload_from_string(b"", content_type="application/octet-stream")

        await asyncio.to_thread(_create_flag)
