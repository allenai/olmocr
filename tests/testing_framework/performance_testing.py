"""
Performance testing framework for OLMoCR.

This module provides performance testing utilities, benchmarking tools,
and regression detection capabilities.
"""

import json
import os
import statistics
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Union

try:
    from olmocr.error_handling import create_logger
except ImportError:
    import logging
    def create_logger(name):
        return logging.getLogger(name)


@dataclass
class PerformanceMetrics:
    """Performance metrics for a test run."""
    
    test_name: str
    duration: float  # Average duration in seconds
    min_duration: float
    max_duration: float
    std_deviation: float
    iterations: int
    throughput: float  # Operations per second
    error_rate: float
    memory_usage: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary."""
        return {
            'test_name': self.test_name,
            'duration': self.duration,
            'min_duration': self.min_duration,
            'max_duration': self.max_duration,
            'std_deviation': self.std_deviation,
            'iterations': self.iterations,
            'throughput': self.throughput,
            'error_rate': self.error_rate,
            'memory_usage': self.memory_usage
        }


class PerformanceTestRunner:
    """Runner for performance tests and benchmarks."""
    
    def __init__(self, logger: Optional[Any] = None):
        """Initialize performance test runner."""
        self.logger = logger or create_logger("PerformanceTestRunner")
        self.baseline_file = "tests/performance_baselines.json"
        self.regression_threshold = 0.1  # 10% performance degradation threshold
    
    def run_performance_test(self, test_name: str, test_func: Callable, 
                           iterations: int = 10, warmup_iterations: int = 2,
                           *args, **kwargs) -> PerformanceMetrics:
        """
        Run a performance test with multiple iterations.
        
        Args:
            test_name: Name of the test
            test_func: Function to test
            iterations: Number of test iterations
            warmup_iterations: Number of warmup iterations
            *args: Arguments for test function
            **kwargs: Keyword arguments for test function
            
        Returns:
            Performance metrics
        """
        self.logger.info(f"Running performance test: {test_name}")
        
        # Warmup iterations
        for i in range(warmup_iterations):
            try:
                test_func(*args, **kwargs)
            except Exception as e:
                self.logger.warning(f"Warmup iteration {i+1} failed: {e}")
        
        # Actual test iterations
        durations = []
        errors = 0
        
        for i in range(iterations):
            start_time = time.time()
            try:
                test_func(*args, **kwargs)
                end_time = time.time()
                durations.append(end_time - start_time)
            except Exception as e:
                errors += 1
                self.logger.warning(f"Test iteration {i+1} failed: {e}")
                # Still record the time for failed operations
                end_time = time.time()
                durations.append(end_time - start_time)
        
        # Calculate metrics
        if durations:
            avg_duration = statistics.mean(durations)
            min_duration = min(durations)
            max_duration = max(durations)
            std_dev = statistics.stdev(durations) if len(durations) > 1 else 0.0
            throughput = 1.0 / avg_duration if avg_duration > 0 else 0.0
        else:
            avg_duration = min_duration = max_duration = std_dev = throughput = 0.0
        
        error_rate = errors / iterations if iterations > 0 else 0.0
        
        metrics = PerformanceMetrics(
            test_name=test_name,
            duration=avg_duration,
            min_duration=min_duration,
            max_duration=max_duration,
            std_deviation=std_dev,
            iterations=iterations,
            throughput=throughput,
            error_rate=error_rate
        )
        
        self.logger.info(f"Performance test completed: {test_name} - "
                        f"{avg_duration:.4f}s avg, {error_rate:.1%} error rate")
        
        return metrics
    
    def benchmark_function(self, func: Callable, iterations: int = 100, 
                          warmup: int = 10, *args, **kwargs) -> PerformanceMetrics:
        """
        Benchmark a function with statistical analysis.
        
        Args:
            func: Function to benchmark
            iterations: Number of iterations
            warmup: Number of warmup iterations
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            Performance metrics
        """
        func_name = getattr(func, '__name__', 'anonymous_function')
        return self.run_performance_test(
            func_name, func, iterations, warmup, *args, **kwargs
        )
    
    def compare_with_baseline(self, metrics: PerformanceMetrics) -> Dict[str, Any]:
        """
        Compare performance metrics with baseline.
        
        Args:
            metrics: Current performance metrics
            
        Returns:
            Comparison results
        """
        baseline = self._load_baseline(metrics.test_name)
        
        if not baseline:
            self.logger.info(f"No baseline found for {metrics.test_name}, creating new baseline")
            self._save_baseline(metrics)
            return {
                'has_baseline': False,
                'is_regression': False,
                'performance_change': 0.0,
                'message': 'New baseline created'
            }
        
        # Calculate performance change
        baseline_duration = baseline.get('duration', 0.0)
        if baseline_duration > 0:
            performance_change = (metrics.duration - baseline_duration) / baseline_duration
        else:
            performance_change = 0.0
        
        is_regression = performance_change > self.regression_threshold
        
        comparison = {
            'has_baseline': True,
            'is_regression': is_regression,
            'performance_change': performance_change,
            'baseline_duration': baseline_duration,
            'current_duration': metrics.duration,
            'threshold': self.regression_threshold
        }
        
        if is_regression:
            comparison['message'] = f"Performance regression detected: {performance_change:.1%} slower"
            self.logger.warning(f"Performance regression in {metrics.test_name}: "
                              f"{performance_change:.1%} slower than baseline")
        else:
            comparison['message'] = f"Performance within acceptable range: {performance_change:.1%} change"
            self.logger.info(f"Performance acceptable for {metrics.test_name}: "
                           f"{performance_change:.1%} change from baseline")
        
        return comparison
    
    def _load_baseline(self, test_name: str) -> Optional[Dict[str, Any]]:
        """Load baseline performance data."""
        try:
            if os.path.exists(self.baseline_file):
                with open(self.baseline_file, 'r') as f:
                    baselines = json.load(f)
                return baselines.get(test_name)
        except Exception as e:
            self.logger.error(f"Failed to load baseline for {test_name}: {e}")
        
        return None
    
    def _save_baseline(self, metrics: PerformanceMetrics):
        """Save baseline performance data."""
        try:
            # Load existing baselines
            baselines = {}
            if os.path.exists(self.baseline_file):
                with open(self.baseline_file, 'r') as f:
                    baselines = json.load(f)
            
            # Update with new baseline
            baselines[metrics.test_name] = metrics.to_dict()
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.baseline_file), exist_ok=True)
            
            # Save updated baselines
            with open(self.baseline_file, 'w') as f:
                json.dump(baselines, f, indent=2)
            
            self.logger.info(f"Saved baseline for {metrics.test_name}")
            
        except Exception as e:
            self.logger.error(f"Failed to save baseline for {metrics.test_name}: {e}")


class RegressionTestSuite:
    """Test suite for performance regression detection."""
    
    def __init__(self, baseline_file: str = "tests/performance_baselines.json"):
        """Initialize regression test suite."""
        self.baseline_file = baseline_file
        self.logger = create_logger("RegressionTestSuite")
        self.performance_runner = PerformanceTestRunner(self.logger)
    
    def run_regression_tests(self, test_suite: Dict[str, tuple]) -> Dict[str, Any]:
        """
        Run regression tests against performance baselines.
        
        Args:
            test_suite: Dictionary mapping test names to (func, args, kwargs) tuples
            
        Returns:
            Regression test results
        """
        self.logger.info("Running performance regression tests")
        
        results = {
            'total_tests': len(test_suite),
            'passed': 0,
            'regressions': 0,
            'new_baselines': 0,
            'test_results': {},
            'summary': {}
        }
        
        for test_name, (test_func, args, kwargs) in test_suite.items():
            try:
                # Run performance test
                metrics = self.performance_runner.run_performance_test(
                    test_name, test_func, iterations=10, warmup_iterations=2,
                    *args, **kwargs
                )
                
                # Compare with baseline
                comparison = self.performance_runner.compare_with_baseline(metrics)
                
                # Record results
                test_result = {
                    'metrics': metrics.to_dict(),
                    'comparison': comparison,
                    'status': 'regression' if comparison['is_regression'] else 'passed'
                }
                
                results['test_results'][test_name] = test_result
                
                if comparison['is_regression']:
                    results['regressions'] += 1
                elif not comparison['has_baseline']:
                    results['new_baselines'] += 1
                else:
                    results['passed'] += 1
                
            except Exception as e:
                self.logger.error(f"Regression test failed for {test_name}: {e}")
                results['test_results'][test_name] = {
                    'status': 'error',
                    'error': str(e)
                }
        
        # Generate summary
        results['summary'] = {
            'success_rate': results['passed'] / results['total_tests'] if results['total_tests'] > 0 else 0.0,
            'regression_rate': results['regressions'] / results['total_tests'] if results['total_tests'] > 0 else 0.0,
            'has_regressions': results['regressions'] > 0
        }
        
        self.logger.info(f"Regression tests completed: {results['passed']} passed, "
                        f"{results['regressions']} regressions, {results['new_baselines']} new baselines")
        
        return results


class PerformanceBenchmark:
    """Benchmark suite for OLMoCR components."""
    
    def __init__(self):
        """Initialize performance benchmark."""
        self.logger = create_logger("PerformanceBenchmark")
        self.runner = PerformanceTestRunner(self.logger)
        self.benchmarks = {}
    
    def add_benchmark(self, name: str, func: Callable, *args, **kwargs):
        """Add a benchmark to the suite."""
        self.benchmarks[name] = (func, args, kwargs)
    
    def run_all_benchmarks(self, iterations: int = 50) -> Dict[str, PerformanceMetrics]:
        """Run all benchmarks in the suite."""
        results = {}
        
        for name, (func, args, kwargs) in self.benchmarks.items():
            metrics = self.runner.run_performance_test(
                name, func, iterations=iterations, warmup_iterations=5,
                *args, **kwargs
            )
            results[name] = metrics
        
        return results
    
    def generate_benchmark_report(self, results: Dict[str, PerformanceMetrics]) -> str:
        """Generate a benchmark report."""
        report_lines = []
        
        report_lines.append("=" * 60)
        report_lines.append("OLMOCR PERFORMANCE BENCHMARK REPORT")
        report_lines.append("=" * 60)
        report_lines.append("")
        
        # Sort by duration
        sorted_results = sorted(results.items(), key=lambda x: x[1].duration)
        
        for name, metrics in sorted_results:
            report_lines.append(f"📊 {name}:")
            report_lines.append(f"   Duration: {metrics.duration:.4f}s ± {metrics.std_deviation:.4f}s")
            report_lines.append(f"   Throughput: {metrics.throughput:.2f} ops/sec")
            report_lines.append(f"   Error Rate: {metrics.error_rate:.1%}")
            report_lines.append(f"   Range: {metrics.min_duration:.4f}s - {metrics.max_duration:.4f}s")
            report_lines.append("")
        
        report_lines.append("=" * 60)
        
        return "\n".join(report_lines)


def benchmark_function(func: Callable, iterations: int = 100, warmup: int = 10,
                      *args, **kwargs) -> PerformanceMetrics:
    """
    Convenience function to benchmark a single function.
    
    Args:
        func: Function to benchmark
        iterations: Number of iterations
        warmup: Number of warmup iterations
        *args: Function arguments
        **kwargs: Function keyword arguments
        
    Returns:
        Performance metrics
    """
    runner = PerformanceTestRunner()
    return runner.benchmark_function(func, iterations, warmup, *args, **kwargs)


def create_performance_baseline(test_suite: Dict[str, tuple], 
                              baseline_file: str = "tests/performance_baselines.json"):
    """
    Create performance baselines for a test suite.
    
    Args:
        test_suite: Dictionary mapping test names to (func, args, kwargs) tuples
        baseline_file: File to save baselines to
    """
    runner = PerformanceTestRunner()
    runner.baseline_file = baseline_file
    
    for test_name, (test_func, args, kwargs) in test_suite.items():
        metrics = runner.run_performance_test(
            test_name, test_func, iterations=20, warmup_iterations=5,
            *args, **kwargs
        )
        runner._save_baseline(metrics)
