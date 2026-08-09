import unittest

from olmocr.prompts.prompts import build_no_anchoring_v4_yaml_prompt


class TestBuildNoAnchoringV4YamlPrompt(unittest.TestCase):
    def test_default_page_num_is_one(self):
        prompt = build_no_anchoring_v4_yaml_prompt()
        self.assertIn("](1_startx_starty_width_height.png)", prompt)

    def test_explicit_page_num_is_interpolated(self):
        prompt = build_no_anchoring_v4_yaml_prompt(page_num=5)
        self.assertIn("](5_startx_starty_width_height.png)", prompt)
        self.assertNotIn("page_startx_starty_width_height.png", prompt)


if __name__ == "__main__":
    unittest.main()
