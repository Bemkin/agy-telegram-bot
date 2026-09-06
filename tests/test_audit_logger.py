"""
test_audit_logger.py — Unit tests for audit logging, file extraction, and history tracking.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import audit_logger


class TestAuditLogger(unittest.TestCase):

    def setUp(self):
        # Create temp dir for isolated test logs
        self.test_dir = tempfile.mkdtemp()
        self.orig_logs_dir = audit_logger.LOGS_DIR
        self.orig_history_json = audit_logger.HISTORY_JSON

        audit_logger.LOGS_DIR = Path(self.test_dir) / "logs"
        audit_logger.LOGS_DIR.mkdir(parents=True, exist_ok=True)
        audit_logger.HISTORY_JSON = audit_logger.LOGS_DIR / "history.json"

    def tearDown(self):
        audit_logger.LOGS_DIR = self.orig_logs_dir
        audit_logger.HISTORY_JSON = self.orig_history_json
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_extract_files_from_text(self):
        sample_text = (
            "I modified src/components/Header.tsx and updated vite.config.ts. "
            "Also check server.py and utils/currency.js."
        )
        files = audit_logger.extract_files_from_text(sample_text)
        self.assertIn("src/components/Header.tsx", files)
        self.assertIn("vite.config.ts", files)
        self.assertIn("server.py", files)
        self.assertIn("utils/currency.js", files)

    def test_log_interaction_creates_markdown_and_json(self):
        proj_dir = Path(self.test_dir) / "test_project"
        proj_dir.mkdir(parents=True, exist_ok=True)

        prompt = "Add currency formatting for Ethiopian Birr (ETB)"
        response = "Created src/utils/currency.ts with formatETB() function."

        log_file = audit_logger.log_interaction(
            prompt=prompt,
            response=response,
            project_dir=str(proj_dir),
            model_name="gemini-2.5-flash",
            user_id=425667436,
            mode="act",
        )

        # Verify global markdown log was created and contains content
        self.assertTrue(log_file.exists())
        content = log_file.read_text(encoding="utf-8")
        self.assertIn(prompt, content)
        self.assertIn("src/utils/currency.ts", content)

        # Verify project-level .agent/audit.md was created
        proj_audit = proj_dir / ".agent" / "audit.md"
        self.assertTrue(proj_audit.exists())
        self.assertIn(prompt, proj_audit.read_text(encoding="utf-8"))

        # Verify structured JSON history
        history = audit_logger.get_structured_history(str(proj_dir))
        self.assertEqual(len(history), 1)
        record = history[0]
        self.assertEqual(record["prompt"], prompt)
        self.assertIn("src/utils/currency.ts", record["files"])
        self.assertEqual(record["model"], "gemini-2.5-flash")


if __name__ == "__main__":
    unittest.main()
