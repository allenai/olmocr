
import time
import asyncio

from collections import defaultdict, deque
from typing import Any, Deque, Dict, List, Set


class MetricsKeeper:
    def __init__(self, window=60 * 5):
        """
        Initializes the MetricsKeeper.

        Args:
            window (int): Time window in seconds for recent metrics. Defaults to 5 minutes.
        """
        self.window = window  # Time window in seconds
        self.start_time = time.time()  # Timestamp when MetricsKeeper was created
        self.total_metrics = defaultdict(int)  # Cumulative metrics since start
        self.window_metrics: Deque[Any] = deque()  # Deque to store (timestamp, metrics_dict)
        self.window_sum = defaultdict(int)  # Sum of metrics within the window

    def add_metrics(self, **kwargs):
        """
        Adds metrics to the keeper.

        Args:
            **kwargs: Arbitrary keyword arguments representing metric names and their values.
        """
        current_time = time.time()
        # Update cumulative metrics
        for key, value in kwargs.items():
            self.total_metrics[key] += value

        # Append current metrics with timestamp to the deque
        self.window_metrics.append((current_time, kwargs))

        # Update window sums
        for key, value in kwargs.items():
            self.window_sum[key] += value

        # Remove metrics that are outside the time window
        while self.window_metrics and self.window_metrics[0][0] < current_time - self.window:
            old_time, old_metrics = self.window_metrics.popleft()
            for key, value in old_metrics.items():
                self.window_sum[key] -= value
                if self.window_sum[key] <= 0:
                    del self.window_sum[key]  # Clean up to prevent negative counts

    def __str__(self):
        """
        Returns a formatted string of metrics showing tokens/sec since start and within the window.

        Returns:
            str: Formatted metrics string as a table.
        """
        current_time = time.time()
        elapsed_time = current_time - self.start_time
        window_time = min(self.window, elapsed_time) if elapsed_time > 0 else 1  # Prevent division by zero

        # Header
        header = f"{'Metric Name':<30} {'Lifetime (tokens/sec)':>25} {'Recently (tokens/sec)':>25}"
        separator = "-" * len(header)
        lines = [header, separator]

        # Sort metrics alphabetically for consistency
        for key in sorted(self.total_metrics.keys()):
            total = self.total_metrics[key]
            window = self.window_sum.get(key, 0)
            total_rate = total / elapsed_time if elapsed_time > 0 else 0
            window_rate = window / window_time if window_time > 0 else 0
            line = f"{key:<20} {total_rate:>25.2f} {window_rate:>25.2f}"
            lines.append(line)

        return "\n".join(lines)


class WorkerTracker:
    def __init__(self):
        """
        Initializes the WorkerTracker with a default dictionary.
        Each worker ID maps to another dictionary that holds counts for each state.
        """
        # Mapping from worker_id to a dictionary of state counts
        self.worker_status: Dict[int, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.lock = asyncio.Lock()

    async def clear_work(self, worker_id: int):
        async with self.lock:
            self.worker_status[worker_id].clear()

    async def track_work(self, worker_id: int, work_item_id: str, state: str):
        """
        Update the state count for a specific worker.

        Args:
            worker_id (int): The ID of the worker.
            work_item_id (str): The unique identifier of the work item (unused in this implementation).
            state (str): The state to increment for the work item.
        """
        async with self.lock:
            self.worker_status[worker_id][state] += 1

    async def get_status_table(self) -> str:
        """
        Generate a formatted table of the current status of all workers.

        Returns:
            str: A string representation of the workers' statuses.
        """
        async with self.lock:
            # Determine all unique states across all workers
            all_states: Set[str] = set()
            for states in self.worker_status.values():
                all_states.update(states.keys())
            sorted_states: List[str] = sorted(all_states)

            headers = ["Worker ID"] + sorted_states  # type: ignore
            rows = []
            for worker_id, states in sorted(self.worker_status.items()):
                row = [str(worker_id)]
                for state in sorted_states:
                    count = states.get(state, 0)
                    row.append(str(count))
                rows.append(row)

            # Calculate column widths
            col_widths = [len(header) for header in headers]
            for row in rows:
                for idx, cell in enumerate(row):
                    col_widths[idx] = max(col_widths[idx], len(cell))

            # Create the table header
            header_line = " | ".join(header.ljust(col_widths[idx]) for idx, header in enumerate(headers))
            separator = "-+-".join("-" * col_widths[idx] for idx in range(len(headers)))

            # Create the table rows
            row_lines = [" | ".join(cell.ljust(col_widths[idx]) for idx, cell in enumerate(row)) for row in rows]

            # Combine all parts
            table = "\n".join([header_line, separator] + row_lines)
            return table

    def __str__(self):
        """
        String representation is not directly supported.
        Use 'await get_status_table()' to retrieve the status table.
        """
        raise NotImplementedError("Use 'await get_status_table()' to get the status table.")
