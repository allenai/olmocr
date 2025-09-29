#!/usr/bin/env python3
"""
Debug script to see what threads are created.
"""

import threading
import time

from olmocr.bench.katex.render import render_equation


def print_threads():
    """Print all active threads."""
    threads = threading.enumerate()
    print(f"Total threads: {len(threads)}")
    for t in threads:
        print(f"  - {t.name} (daemon={t.daemon})")


print("Initial threads:")
print_threads()

print("\nRendering one equation...")
result = render_equation("\\frac{a}{b}", use_cache=False)
print("Render complete")

print("\nThreads after first render:")
print_threads()

print("\nRendering another equation...")
result = render_equation("x^2 + y^2", use_cache=False)
print("Render complete")

print("\nThreads after second render:")
print_threads()

# Wait a bit for any cleanup
time.sleep(2)

print("\nFinal threads:")
print_threads()
