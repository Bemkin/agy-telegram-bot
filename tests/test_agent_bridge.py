"""
test_agent_bridge.py — Unit tests for AgentBridge state management and mode switching.
"""

import shutil
import tempfile
import unittest
from pathlib import Path

from agent_bridge import AgentBridge


class TestAgentBridge(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.proj_dir = Path(self.test_dir) / "sample_app"
        self.proj_dir.mkdir(parents=True, exist_ok=True)
        self.bridge = AgentBridge(project_dir=str(self.proj_dir), model="gemini-2.5-flash")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_initial_state(self):
        status = self.bridge.status()
        self.assertEqual(status["project"], str(self.proj_dir))
        self.assertEqual(status["model"], "gemini-2.5-flash")
        self.assertFalse(status["running"])
        self.assertEqual(self.bridge.mode, "plan")

    def test_mode_switching(self):
        # Switch to plan mode
        res_plan = self.bridge.set_mode("plan")
        self.assertEqual(self.bridge.mode, "plan")
        self.assertIn("Planning Mode", res_plan)

        # Switch to act mode
        res_act = self.bridge.set_mode("act")
        self.assertEqual(self.bridge.mode, "act")
        self.assertIn("Direct Action Mode", res_act)

    def test_switch_project_validates_existence(self):
        import asyncio
        non_existent = str(Path(self.test_dir) / "does_not_exist")
        res = asyncio.run(self.bridge.switch_project(non_existent))
        self.assertIn("Directory does not exist", res)


if __name__ == "__main__":
    unittest.main()
