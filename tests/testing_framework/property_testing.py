"""
Property-based testing framework for OLMoCR.

This module provides property-based testing utilities to generate test cases
and validate invariants across different input combinations.
"""

import random
import string
from typing import Any, Callable, Dict, List, Optional, Tuple, Union


class PropertyTestGenerator:
    """
    Generator for property-based test data.
    
    Provides methods to generate various types of test data for property-based
    testing of OLMoCR components.
    """
    
    def __init__(self, seed: Optional[int] = None):
        """
        Initialize property test generator.
        
        Args:
            seed: Random seed for reproducible tests
        """
        if seed is not None:
            random.seed(seed)
        
        self.iteration_count = 0
    
    def generate_text(self, min_length: int = 1, max_length: int = 1000, 
                     include_special: bool = True) -> str:
        """
        Generate random text for testing.
        
        Args:
            min_length: Minimum text length
            max_length: Maximum text length
            include_special: Include special characters
            
        Returns:
            Random text string
        """
        length = random.randint(min_length, max_length)
        
        chars = string.ascii_letters + string.digits + ' \n\t'
        if include_special:
            chars += string.punctuation
        
        return ''.join(random.choice(chars) for _ in range(length))
    
    def generate_email(self) -> str:
        """Generate a random email address."""
        domains = ['example.com', 'test.org', 'sample.net', 'demo.edu']
        username_length = random.randint(3, 15)
        username = ''.join(random.choice(string.ascii_lowercase + string.digits) 
                          for _ in range(username_length))
        domain = random.choice(domains)
        return f"{username}@{domain}"
    
    def generate_phone(self) -> str:
        """Generate a random phone number."""
        formats = [
            "({}) {}-{}",
            "{}-{}-{}",
            "{}.{}.{}",
            "+1 {} {} {}"
        ]
        
        area_code = random.randint(200, 999)
        exchange = random.randint(200, 999)
        number = random.randint(1000, 9999)
        
        format_str = random.choice(formats)
        return format_str.format(area_code, exchange, number)
    
    def generate_currency(self, min_amount: float = 0.01, max_amount: float = 999999.99) -> str:
        """Generate a random currency amount."""
        amount = random.uniform(min_amount, max_amount)
        currencies = ['$', '€', '£', '¥']
        currency = random.choice(currencies)
        
        # Format with appropriate decimal places
        if amount >= 1000:
            return f"{currency}{amount:,.2f}"
        else:
            return f"{currency}{amount:.2f}"
    
    def generate_date(self) -> str:
        """Generate a random date string."""
        formats = [
            "{:02d}/{:02d}/{:04d}",
            "{:04d}-{:02d}-{:02d}",
            "{:02d}.{:02d}.{:04d}",
            "{} {:02d}, {:04d}"
        ]
        
        year = random.randint(1990, 2030)
        month = random.randint(1, 12)
        day = random.randint(1, 28)  # Safe day range
        
        format_str = random.choice(formats)
        
        if "{}" in format_str and "," in format_str:
            # Month name format
            months = ['January', 'February', 'March', 'April', 'May', 'June',
                     'July', 'August', 'September', 'October', 'November', 'December']
            return format_str.format(months[month-1], day, year)
        else:
            return format_str.format(month, day, year)
    
    def generate_key_value_pair(self) -> Tuple[str, str]:
        """Generate a random key-value pair."""
        keys = [
            'name', 'email', 'phone', 'address', 'city', 'state', 'zip',
            'company', 'title', 'salary', 'date', 'amount', 'total',
            'description', 'quantity', 'price', 'tax', 'discount'
        ]
        
        key = random.choice(keys)
        
        # Generate appropriate value based on key
        if 'email' in key.lower():
            value = self.generate_email()
        elif 'phone' in key.lower():
            value = self.generate_phone()
        elif any(word in key.lower() for word in ['amount', 'salary', 'price', 'total', 'tax']):
            value = self.generate_currency()
        elif 'date' in key.lower():
            value = self.generate_date()
        else:
            value = self.generate_text(min_length=3, max_length=50, include_special=False)
        
        return key, value
    
    def generate_table_data(self, min_rows: int = 1, max_rows: int = 10,
                           min_cols: int = 2, max_cols: int = 6) -> Tuple[List[str], List[List[str]]]:
        """
        Generate random table data.
        
        Args:
            min_rows: Minimum number of rows
            max_rows: Maximum number of rows
            min_cols: Minimum number of columns
            max_cols: Maximum number of columns
            
        Returns:
            Tuple of (headers, rows)
        """
        num_cols = random.randint(min_cols, max_cols)
        num_rows = random.randint(min_rows, max_rows)
        
        # Generate headers
        header_words = ['Name', 'ID', 'Amount', 'Date', 'Status', 'Type', 'Category',
                       'Description', 'Quantity', 'Price', 'Total', 'Region', 'Sales']
        headers = random.sample(header_words, min(num_cols, len(header_words)))
        
        # Pad with generic headers if needed
        while len(headers) < num_cols:
            headers.append(f"Column{len(headers) + 1}")
        
        # Generate rows
        rows = []
        for _ in range(num_rows):
            row = []
            for col_idx in range(num_cols):
                header = headers[col_idx].lower()
                
                # Generate appropriate data based on header
                if 'amount' in header or 'price' in header or 'total' in header:
                    cell_value = self.generate_currency()
                elif 'date' in header:
                    cell_value = self.generate_date()
                elif 'id' in header:
                    cell_value = str(random.randint(1000, 9999))
                elif 'quantity' in header:
                    cell_value = str(random.randint(1, 100))
                else:
                    cell_value = self.generate_text(min_length=3, max_length=20, include_special=False)
                
                row.append(cell_value)
            
            rows.append(row)
        
        return headers, rows
    
    def generate_document_content(self, doc_type: str) -> str:
        """
        Generate document content based on type.
        
        Args:
            doc_type: Type of document to generate
            
        Returns:
            Generated document content
        """
        if doc_type == "form" or doc_type == "FORM":
            return self._generate_form_content()
        elif doc_type == "invoice" or doc_type == "INVOICE":
            return self._generate_invoice_content()
        elif doc_type == "table" or doc_type == "TABLE":
            return self._generate_table_content()
        elif doc_type == "contract" or doc_type == "CONTRACT":
            return self._generate_contract_content()
        else:
            return self._generate_mixed_content()
    
    def _generate_form_content(self) -> str:
        """Generate form content."""
        content = "APPLICATION FORM\n\n"
        
        # Generate random form fields
        num_fields = random.randint(5, 15)
        for _ in range(num_fields):
            key, value = self.generate_key_value_pair()
            content += f"{key.title()}: {value}\n"
        
        content += f"\nSignature: {self.generate_text(min_length=5, max_length=20, include_special=False)}\n"
        content += f"Date: {self.generate_date()}\n"
        
        return content
    
    def _generate_invoice_content(self) -> str:
        """Generate invoice content."""
        invoice_num = random.randint(1000, 9999)
        content = f"INVOICE #{invoice_num}\n\n"
        
        content += f"Bill To: {self.generate_text(min_length=10, max_length=30, include_special=False)}\n"
        content += f"Invoice Date: {self.generate_date()}\n"
        content += f"Due Date: {self.generate_date()}\n\n"
        
        # Generate line items table
        headers, rows = self.generate_table_data(min_rows=2, max_rows=8, min_cols=3, max_cols=4)
        content += "| " + " | ".join(headers) + " |\n"
        content += "|" + "|".join(["-" * (len(h) + 2) for h in headers]) + "|\n"
        
        for row in rows:
            content += "| " + " | ".join(row) + " |\n"
        
        content += f"\nTotal: {self.generate_currency()}\n"
        
        return content
    
    def _generate_table_content(self) -> str:
        """Generate table content."""
        content = f"{self.generate_text(min_length=10, max_length=30, include_special=False).upper()}\n\n"
        
        headers, rows = self.generate_table_data(min_rows=3, max_rows=12)
        content += "| " + " | ".join(headers) + " |\n"
        content += "|" + "|".join(["-" * (len(h) + 2) for h in headers]) + "|\n"
        
        for row in rows:
            content += "| " + " | ".join(row) + " |\n"
        
        return content
    
    def _generate_contract_content(self) -> str:
        """Generate contract content."""
        content = "AGREEMENT\n\n"
        content += f"This agreement is made between {self.generate_text(min_length=10, max_length=25, include_special=False)} "
        content += f"and {self.generate_text(min_length=10, max_length=25, include_special=False)}.\n\n"
        
        # Add some contract terms
        num_terms = random.randint(3, 8)
        for i in range(num_terms):
            content += f"{i+1}. {self.generate_text(min_length=20, max_length=100, include_special=False)}\n"
        
        content += f"\nEffective Date: {self.generate_date()}\n"
        content += f"Expiration Date: {self.generate_date()}\n"
        
        return content
    
    def _generate_mixed_content(self) -> str:
        """Generate mixed content."""
        content = f"{self.generate_text(min_length=10, max_length=30, include_special=False).upper()}\n\n"
        
        # Add some text
        content += self.generate_text(min_length=50, max_length=200) + "\n\n"
        
        # Add some key-value pairs
        num_fields = random.randint(2, 6)
        for _ in range(num_fields):
            key, value = self.generate_key_value_pair()
            content += f"{key.title()}: {value}\n"
        
        content += "\n"
        
        # Add a table
        headers, rows = self.generate_table_data(min_rows=2, max_rows=5)
        content += "| " + " | ".join(headers) + " |\n"
        content += "|" + "|".join(["-" * (len(h) + 2) for h in headers]) + "|\n"
        
        for row in rows:
            content += "| " + " | ".join(row) + " |\n"
        
        return content


class DocumentPropertyTests:
    """Property tests for document processing."""
    
    @staticmethod
    def test_document_processing_preserves_content(processor_func: Callable, content: str) -> bool:
        """Test that document processing preserves essential content."""
        try:
            result = processor_func(content)
            
            # Basic invariants
            if result is None:
                return False
            
            # Content should not be empty if input wasn't empty
            if content.strip() and not str(result).strip():
                return False
            
            return True
            
        except Exception:
            return False


class StructuredOutputPropertyTests:
    """Property tests for structured output functionality."""
    
    @staticmethod
    def test_field_extraction_consistency(extractor_func: Callable, field_value: str) -> bool:
        """Test that field type detection is consistent."""
        try:
            # Run extraction multiple times
            results = [extractor_func(field_value) for _ in range(3)]
            
            # Results should be consistent
            if len(set(str(r) for r in results)) > 1:
                return False
            
            return True
            
        except Exception:
            return False


def run_property_tests(test_func: Callable, generator_func: Callable, 
                      iterations: int = 100) -> Dict[str, Any]:
    """
    Run property-based tests.
    
    Args:
        test_func: Test function to run
        generator_func: Function to generate test data
        iterations: Number of test iterations
        
    Returns:
        Test results summary
    """
    results = {
        'total_iterations': iterations,
        'passed': 0,
        'failed': 0,
        'errors': [],
        'success_rate': 0.0
    }
    
    for i in range(iterations):
        try:
            test_data = generator_func()
            if isinstance(test_data, tuple):
                passed = test_func(*test_data)
            else:
                passed = test_func(test_data)
            
            if passed:
                results['passed'] += 1
            else:
                results['failed'] += 1
                results['errors'].append(f"Iteration {i}: Test failed")
                
        except Exception as e:
            results['failed'] += 1
            results['errors'].append(f"Iteration {i}: {str(e)}")
    
    results['success_rate'] = results['passed'] / iterations if iterations > 0 else 0.0
    
    return results
