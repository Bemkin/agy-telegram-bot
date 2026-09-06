"""
test_message_formatter.py — Unit tests for message formatting and 4096-char chunk splitting.
"""

import unittest
from message_formatter import format_for_telegram, split_message


class TestMessageFormatter(unittest.TestCase):

    def test_format_for_telegram_converts_markdown(self):
        md = "# Heading\n**Bold Text** and `inline_code`\n```python\nprint('hello')\n```"
        formatted = format_for_telegram(md)

        self.assertIn("<b>Heading</b>", formatted)
        self.assertIn("<b>Bold Text</b>", formatted)
        self.assertIn("<code>inline_code</code>", formatted)
        self.assertIn("<pre>", formatted)

    def test_split_message_under_limit_returns_single_chunk(self):
        text = "Hello world! This is a standard short message."
        chunks = split_message(text, max_len=1000)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], text)

    def test_split_message_over_limit(self):
        long_body = "Line of code with important details.\n" * 150
        text = f"<b>Title</b>\n{long_body}"

        chunks = split_message(text, max_len=1000)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= 1000 for c in chunks))


if __name__ == "__main__":
    unittest.main()
