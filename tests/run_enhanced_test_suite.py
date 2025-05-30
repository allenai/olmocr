#!/usr/bin/env python3
"""
Enhanced test suite runner for OLMoCR.

This script runs the comprehensive test suite with coverage analysis,
performance benchmarking, and detailed reporting.
"""

import argparse
import json
import os
import sys
import time
import unittest
from typing import Dict, List, Any

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.testing_framework import (
    TestResultAggregator, generate_coverage_report,
    PerformanceTestRunner, RegressionTestSuite,
    create_performance_baseline
)
from olmocr.error_handling import create_logger


class EnhancedTestSuiteRunner:
    """Enhanced test suite runner with comprehensive reporting."""
    
    def __init__(self, verbose: bool = True):
        """Initialize the test suite runner."""
        self.verbose = verbose
        self.logger = create_logger("EnhancedTestSuiteRunner")
        self.result_aggregator = TestResultAggregator()
        self.performance_runner = PerformanceTestRunner(self.logger)
        
        # Test modules to run
        self.test_modules = [
            'tests.test_enhanced_pipeline_comprehensive',
            'tests.test_structured_output_integration',
            'tests.test_structured_output',  # From structured output implementation
        ]
        
        # Performance test functions
        self.performance_tests = {}
    
    def discover_test_modules(self) -> List[str]:
        """Discover all test modules in the tests directory."""
        test_modules = []
        tests_dir = os.path.dirname(__file__)
        
        for filename in os.listdir(tests_dir):
            if filename.startswith('test_') and filename.endswith('.py'):
                module_name = f"tests.{filename[:-3]}"
                test_modules.append(module_name)
        
        return test_modules
    
    def run_unit_tests(self, test_pattern: str = "test_*") -> Dict[str, Any]:
        """
        Run unit tests with detailed reporting.
        
        Args:
            test_pattern: Pattern to match test files
            
        Returns:
            Test results summary
        """
        self.logger.info("Running unit tests...")
        
        # Discover and load tests
        loader = unittest.TestLoader()
        suite = unittest.TestSuite()
        
        # Add tests from specified modules
        for module_name in self.test_modules:
            try:
                module_suite = loader.loadTestsFromName(module_name)
                suite.addTest(module_suite)
                self.logger.info(f"Added tests from {module_name}")
            except Exception as e:
                self.logger.warning(f"Failed to load tests from {module_name}: {e}")
        
        # Run tests
        runner = unittest.TextTestRunner(
            verbosity=2 if self.verbose else 1,
            stream=sys.stdout,
            buffer=True
        )
        
        start_time = time.time()
        result = runner.run(suite)
        end_time = time.time()
        
        # Aggregate results
        test_summary = {
            'total_tests': result.testsRun,
            'failures': len(result.failures),
            'errors': len(result.errors),
            'skipped': len(result.skipped) if hasattr(result, 'skipped') else 0,
            'success_rate': ((result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100) if result.testsRun > 0 else 0,
            'duration': end_time - start_time,
            'successful': result.wasSuccessful()
        }
        
        # Add individual test results to aggregator
        for test, error in result.failures:
            self.result_aggregator.add_result(str(test), 'failed', error_info=error)
        
        for test, error in result.errors:
            self.result_aggregator.add_result(str(test), 'error', error_info=error)
        
        # Add successful tests
        successful_tests = result.testsRun - len(result.failures) - len(result.errors)
        for i in range(successful_tests):
            self.result_aggregator.add_result(f"successful_test_{i}", 'passed')
        
        return test_summary
    
    def run_performance_tests(self) -> Dict[str, Any]:
        """Run performance tests and benchmarks."""
        self.logger.info("Running performance tests...")
        
        performance_results = {}
        
        # Define performance test functions
        def test_document_building():
            """Test document building performance."""
            try:
                from olmocr.pipeline.document_builder import build_dolma_document
                from tests.testing_framework.fixtures import MockPageResult
                
                page_results = [MockPageResult(i, f"Page {i} content") for i in range(1, 6)]
                return build_dolma_document("perf_test.pdf", page_results)
            except ImportError:
                return None
        
        def test_structured_output_processing():
            """Test structured output processing performance."""
            try:
                from olmocr.structured_output import create_structured_output_config, create_structured_output_processor
                from tests.testing_framework.fixtures import TestFixtures
                
                config = create_structured_output_config()
                processor = create_structured_output_processor(config)
                content = TestFixtures.create_sample_form_content()
                return processor.process_document("perf_test", content)
            except ImportError:
                return None
        
        # Run performance tests
        performance_tests = {
            'document_building': test_document_building,
            'structured_output_processing': test_structured_output_processing,
        }
        
        for test_name, test_func in performance_tests.items():
            try:
                if test_func() is not None:  # Check if test can run
                    metrics = self.performance_runner.run_performance_test(
                        test_name, test_func, iterations=10, warmup_iterations=2
                    )
                    performance_results[test_name] = {
                        'duration': metrics.duration,
                        'throughput': metrics.throughput,
                        'error_rate': metrics.error_rate,
                        'iterations': metrics.iterations
                    }
                else:
                    performance_results[test_name] = {'status': 'skipped', 'reason': 'dependencies not available'}
            except Exception as e:
                performance_results[test_name] = {'status': 'error', 'error': str(e)}
                self.logger.error(f"Performance test {test_name} failed: {e}")
        
        return performance_results
    
    def run_regression_tests(self) -> Dict[str, Any]:
        """Run regression tests against performance baselines."""
        self.logger.info("Running regression tests...")
        
        try:
            regression_suite = RegressionTestSuite("tests/performance_baselines.json")
            
            # Define regression test suite
            test_suite = {}
            
            # Add document building test
            try:
                from olmocr.pipeline.document_builder import build_dolma_document
                from tests.testing_framework.fixtures import MockPageResult
                
                def regression_document_building():
                    page_results = [MockPageResult(i, f"Page {i}") for i in range(1, 4)]
                    return build_dolma_document("regression_test.pdf", page_results)
                
                test_suite['document_building_regression'] = (regression_document_building, (), {})
            except ImportError:
                pass
            
            # Add structured output test
            try:
                from olmocr.structured_output import create_structured_output_config, create_structured_output_processor
                
                def regression_structured_output():
                    config = create_structured_output_config()
                    processor = create_structured_output_processor(config)
                    return processor.process_document("regression_test", "Name: Test User\nEmail: test@example.com")
                
                test_suite['structured_output_regression'] = (regression_structured_output, (), {})
            except ImportError:
                pass
            
            # Run regression tests
            if test_suite:
                results = regression_suite.run_regression_tests(test_suite)
                return results
            else:
                return {'status': 'skipped', 'reason': 'no regression tests available'}
                
        except Exception as e:
            self.logger.error(f"Regression tests failed: {e}")
            return {'status': 'error', 'error': str(e)}
    
    def generate_coverage_analysis(self) -> Dict[str, Any]:
        """Generate code coverage analysis."""
        self.logger.info("Generating coverage analysis...")
        
        try:
            # Generate coverage report for the olmocr module
            coverage_data = generate_coverage_report(
                source_root="olmocr",
                output_file="tests/coverage_report.txt"
            )
            
            return {
                'status': 'completed',
                'coverage_data': coverage_data,
                'report_file': 'tests/coverage_report.txt'
            }
            
        except Exception as e:
            self.logger.error(f"Coverage analysis failed: {e}")
            return {'status': 'error', 'error': str(e)}
    
    def run_complete_test_suite(self) -> Dict[str, Any]:
        """Run the complete enhanced test suite."""
        self.logger.info("Starting enhanced test suite...")
        
        start_time = time.time()
        
        # Initialize results
        suite_results = {
            'start_time': start_time,
            'unit_tests': {},
            'performance_tests': {},
            'regression_tests': {},
            'coverage_analysis': {},
            'summary': {}
        }
        
        try:
            # Run unit tests
            print("=" * 80)
            print("🧪 RUNNING UNIT TESTS")
            print("=" * 80)
            suite_results['unit_tests'] = self.run_unit_tests()
            
            # Run performance tests
            print("\n" + "=" * 80)
            print("⚡ RUNNING PERFORMANCE TESTS")
            print("=" * 80)
            suite_results['performance_tests'] = self.run_performance_tests()
            
            # Run regression tests
            print("\n" + "=" * 80)
            print("📈 RUNNING REGRESSION TESTS")
            print("=" * 80)
            suite_results['regression_tests'] = self.run_regression_tests()
            
            # Generate coverage analysis
            print("\n" + "=" * 80)
            print("📊 GENERATING COVERAGE ANALYSIS")
            print("=" * 80)
            suite_results['coverage_analysis'] = self.generate_coverage_analysis()
            
        except Exception as e:
            self.logger.error(f"Test suite execution failed: {e}")
            suite_results['error'] = str(e)
        
        # Calculate summary
        end_time = time.time()
        suite_results['end_time'] = end_time
        suite_results['total_duration'] = end_time - start_time
        
        # Generate summary
        unit_tests = suite_results['unit_tests']
        suite_results['summary'] = {
            'total_duration': suite_results['total_duration'],
            'unit_tests_passed': unit_tests.get('successful', False),
            'unit_test_success_rate': unit_tests.get('success_rate', 0),
            'performance_tests_run': len([t for t in suite_results['performance_tests'].values() 
                                        if isinstance(t, dict) and 'duration' in t]),
            'regression_tests_run': suite_results['regression_tests'].get('total_tests', 0),
            'coverage_generated': suite_results['coverage_analysis'].get('status') == 'completed'
        }
        
        return suite_results
    
    def print_final_report(self, results: Dict[str, Any]):
        """Print final test suite report."""
        print("\n" + "=" * 80)
        print("📋 ENHANCED TEST SUITE FINAL REPORT")
        print("=" * 80)
        
        summary = results['summary']
        
        print(f"⏱️  Total Duration: {summary['total_duration']:.2f} seconds")
        print(f"🧪 Unit Tests: {'✅ PASSED' if summary['unit_tests_passed'] else '❌ FAILED'}")
        print(f"   Success Rate: {summary['unit_test_success_rate']:.1f}%")
        print(f"⚡ Performance Tests: {summary['performance_tests_run']} completed")
        print(f"📈 Regression Tests: {summary['regression_tests_run']} executed")
        print(f"📊 Coverage Analysis: {'✅ Generated' if summary['coverage_generated'] else '❌ Failed'}")
        
        # Unit test details
        unit_tests = results['unit_tests']
        if unit_tests:
            print(f"\n📊 Unit Test Details:")
            print(f"   Total Tests: {unit_tests.get('total_tests', 0)}")
            print(f"   Failures: {unit_tests.get('failures', 0)}")
            print(f"   Errors: {unit_tests.get('errors', 0)}")
            print(f"   Skipped: {unit_tests.get('skipped', 0)}")
        
        # Performance test details
        perf_tests = results['performance_tests']
        if perf_tests:
            print(f"\n⚡ Performance Test Results:")
            for test_name, test_result in perf_tests.items():
                if isinstance(test_result, dict) and 'duration' in test_result:
                    print(f"   {test_name}: {test_result['duration']:.3f}s avg")
        
        # Coverage details
        coverage = results['coverage_analysis']
        if coverage.get('status') == 'completed':
            coverage_data = coverage.get('coverage_data', {})
            if 'summary' in coverage_data:
                coverage_pct = coverage_data['summary'].get('coverage_percentage', 0)
                print(f"\n📊 Code Coverage: {coverage_pct:.1f}%")
        
        print("\n" + "=" * 80)
        
        # Overall status
        overall_success = (
            summary['unit_tests_passed'] and
            summary['coverage_generated']
        )
        
        if overall_success:
            print("🎉 ENHANCED TEST SUITE COMPLETED SUCCESSFULLY!")
        else:
            print("⚠️  ENHANCED TEST SUITE COMPLETED WITH ISSUES")
        
        print("=" * 80)


def main():
    """Main entry point for the enhanced test suite runner."""
    parser = argparse.ArgumentParser(description="Run enhanced OLMoCR test suite")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")
    parser.add_argument("--output", "-o", help="Output file for results (JSON)")
    parser.add_argument("--unit-only", action="store_true", help="Run only unit tests")
    parser.add_argument("--performance-only", action="store_true", help="Run only performance tests")
    parser.add_argument("--coverage-only", action="store_true", help="Run only coverage analysis")
    
    args = parser.parse_args()
    
    # Create test runner
    runner = EnhancedTestSuiteRunner(verbose=args.verbose)
    
    # Run appropriate test suite
    if args.unit_only:
        results = {'unit_tests': runner.run_unit_tests()}
    elif args.performance_only:
        results = {'performance_tests': runner.run_performance_tests()}
    elif args.coverage_only:
        results = {'coverage_analysis': runner.generate_coverage_analysis()}
    else:
        results = runner.run_complete_test_suite()
    
    # Print final report
    runner.print_final_report(results)
    
    # Save results to file if specified
    if args.output:
        try:
            with open(args.output, 'w') as f:
                json.dump(results, f, indent=2, default=str)
            print(f"\n💾 Results saved to {args.output}")
        except Exception as e:
            print(f"\n❌ Failed to save results to {args.output}: {e}")
    
    # Exit with appropriate code
    if 'summary' in results:
        exit_code = 0 if results['summary'].get('unit_tests_passed', False) else 1
    else:
        exit_code = 0 if results.get('unit_tests', {}).get('successful', False) else 1
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
