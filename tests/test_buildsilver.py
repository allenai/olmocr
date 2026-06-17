import unittest

from olmocr.data.buildsilver import sample_pdf_pages


class SamplePdfPagesTest(unittest.TestCase):
    def test_first_n_pages_greater_than_max_sample_pages(self):
        # When first_n_pages exceeds max_sample_pages and the document has more
        # pages than first_n_pages, the number of additional pages to sample is
        # negative. random.sample() rejects a negative sample size, so this used
        # to raise ValueError. The first_n_pages should still be returned.
        result = sample_pdf_pages(num_pages=10, first_n_pages=5, max_sample_pages=3)
        self.assertEqual(result, [1, 2, 3, 4, 5])

    def test_normal_sampling_within_bounds(self):
        result = sample_pdf_pages(num_pages=10, first_n_pages=2, max_sample_pages=5)
        # First two pages always included, plus 3 sampled from pages 3..10.
        self.assertEqual(result[:2], [1, 2])
        self.assertEqual(len(result), 5)
        self.assertTrue(all(3 <= p <= 10 for p in result[2:]))

    def test_fewer_pages_than_first_n(self):
        result = sample_pdf_pages(num_pages=3, first_n_pages=5, max_sample_pages=10)
        self.assertEqual(result, [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
