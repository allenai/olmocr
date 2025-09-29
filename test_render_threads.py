#!/usr/bin/env python3
"""
Test script to verify that the new ThreadPoolExecutor-based render_equation
doesn't leak resources when used from multiple threads.
"""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor as TestThreadPoolExecutor

import psutil

from olmocr.bench.katex.render import render_equation


def monitor_resources():
    """Monitor process resources."""
    process = psutil.Process(os.getpid())

    # Initial state
    initial_threads = threading.active_count()
    initial_memory = process.memory_info().rss / 1024 / 1024  # MB

    print(f"Initial state:")
    print(f"  Active threads: {initial_threads}")
    print(f"  Memory usage: {initial_memory:.2f} MB")

    return initial_threads, initial_memory


def render_task(task_id, num_renders=10):
    """Render equations in a thread."""
    equations = [
        "\\frac{a}{b}",
        "\\sqrt{x^2 + y^2}",
        "\\sum_{i=1}^{n} x_i",
        "\\int_{a}^{b} f(x) dx",
    ]

    for i in range(num_renders):
        eq = equations[i % len(equations)]
        try:
            result = render_equation(eq, use_cache=False)  # Disable cache to force rendering
            if i == 0:
                print(f"Thread {task_id}: First render successful")
        except Exception as e:
            print(f"Thread {task_id}: Error rendering equation: {e}")
            return

    print(f"Thread {task_id}: Completed {num_renders} renders")


def test_concurrent_rendering():
    """Test rendering from multiple threads concurrently."""
    print("Testing concurrent rendering with ThreadPoolExecutor solution...")
    print("-" * 60)

    initial_threads, initial_memory = monitor_resources()

    # Simulate what happens in the RL training loop:
    # Multiple rounds of creating new threads
    for round_num in range(3):
        print(f"\nRound {round_num + 1}: Creating 8 threads...")

        # Create a thread pool that simulates DataLoader workers
        with TestThreadPoolExecutor(max_workers=8) as executor:
            futures = []
            for i in range(8):
                future = executor.submit(render_task, f"R{round_num+1}T{i+1}", 5)
                futures.append(future)

            # Wait for all tasks to complete
            for future in futures:
                future.result()

        # Give a moment for cleanup
        time.sleep(1)

        # Check resources after each round
        process = psutil.Process(os.getpid())
        current_threads = threading.active_count()
        current_memory = process.memory_info().rss / 1024 / 1024

        print(f"\nAfter round {round_num + 1}:")
        print(f"  Active threads: {current_threads} (Δ={current_threads - initial_threads})")
        print(f"  Memory usage: {current_memory:.2f} MB (Δ={current_memory - initial_memory:.2f} MB)")

    # Final check
    time.sleep(2)
    process = psutil.Process(os.getpid())
    final_threads = threading.active_count()
    final_memory = process.memory_info().rss / 1024 / 1024

    print("\n" + "=" * 60)
    print("Final state:")
    print(f"  Active threads: {final_threads} (Δ={final_threads - initial_threads})")
    print(f"  Memory usage: {final_memory:.2f} MB (Δ={final_memory - initial_memory:.2f} MB)")

    # The key test: thread count should be bounded
    # We expect ~4 additional threads from the render executor, plus a few for Python internals
    expected_max_thread_increase = 10
    if final_threads - initial_threads > expected_max_thread_increase:
        print(f"\n⚠️  WARNING: Thread count increased by {final_threads - initial_threads}, expected <= {expected_max_thread_increase}")
        print("This might indicate a resource leak!")
    else:
        print(f"\n✅ Thread count is bounded (increase of {final_threads - initial_threads} threads)")
        print("The ThreadPoolExecutor solution appears to be working correctly!")


if __name__ == "__main__":
    test_concurrent_rendering()
