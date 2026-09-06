"""
test_plan_manager.py — Unit tests for implementation plans and walkthrough tracking.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from plan_manager import PlanManager


class TestPlanManager(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.proj_dir = Path(self.test_dir) / "sample_app"
        self.proj_dir.mkdir(parents=True, exist_ok=True)
        self.mgr = PlanManager(str(self.proj_dir))

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_save_and_get_active_plan(self):
        title = "Build Dark Mode Switcher"
        content = (
            "## Milestones\n"
            "- [ ] Create `src/context/ThemeContext.tsx`\n"
            "- [ ] Add toggle button to `src/components/Navbar.tsx`\n"
            "- [ ] Test persistence in localStorage"
        )

        saved_path = self.mgr.save_plan(title, content)
        self.assertTrue(saved_path.exists())

        active_plan = self.mgr.get_active_plan()
        self.assertIsNotNone(active_plan)
        self.assertIn("Build Dark Mode Switcher", active_plan)
        self.assertIn("ThemeContext.tsx", active_plan)

    def test_save_and_get_walkthrough(self):
        title = "Build Dark Mode Switcher"
        exec_response = (
            "Successfully created `ThemeContext.tsx` and modified `Navbar.tsx`. "
            "Verification passed with 0 TypeScript errors."
        )
        files = ["src/context/ThemeContext.tsx", "src/components/Navbar.tsx"]

        walkthrough_path = self.mgr.save_walkthrough(title, exec_response, files)
        self.assertTrue(walkthrough_path.exists())

        walkthrough_content = self.mgr.get_active_walkthrough()
        self.assertIsNotNone(walkthrough_content)
        self.assertIn("Completed Tasks & Walkthrough: Build Dark Mode Switcher", walkthrough_content)
        self.assertIn("ThemeContext.tsx", walkthrough_content)
        self.assertIn("Navbar.tsx", walkthrough_content)

    def test_list_plans_returns_all_historical_records(self):
        self.mgr.save_plan("Feature 1", "Plan 1 content")
        self.mgr.save_plan("Feature 2", "Plan 2 content")

        plans = self.mgr.list_plans()
        self.assertGreaterEqual(len(plans), 2)


if __name__ == "__main__":
    unittest.main()
