"""
test_server_api.py — Integration tests for FastAPI Mission Control endpoints.
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from plan_manager import PlanManager
from server import app, set_bot_context


class TestServerAPI(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.proj_dir = Path(self.test_dir) / "sample_app"
        self.proj_dir.mkdir(parents=True, exist_ok=True)

        # Mock Bridge
        self.mock_bridge = MagicMock()
        self.mock_bridge.project_dir = str(self.proj_dir)
        self.mock_bridge.model_name = "gemini-2.5-flash"
        self.mock_bridge.mode = "plan"
        self.mock_bridge.chat = AsyncMock(return_value="Mocked AI Agent reply")
        self.mock_bridge.switch_project = AsyncMock(return_value="Switched to new project")

        # Mock Tunnel Manager
        self.mock_tunnel_mgr = MagicMock()
        self.mock_tunnel_mgr.get_status.return_value = {
            "url": "https://test-tunnel.trycloudflare.com",
            "port": 8080,
        }
        self.mock_tunnel_mgr.active_url = "https://test-tunnel.trycloudflare.com"

        # Mock Dev Manager
        self.mock_dev_mgr = MagicMock()
        self.mock_dev_mgr.get_status.return_value = {"running": True, "pid": 1234, "uptime": "10m"}
        self.mock_dev_mgr.get_logs.return_value = ["Vite server started", "ready in 200ms"]

        # Real Plan Manager in temp dir
        self.plan_mgr = PlanManager(str(self.proj_dir))
        self.plan_mgr.save_plan("Test Feature", "- [ ] Task 1 `file1.ts`\n- [x] Task 2 `file2.ts`")
        self.plan_mgr.save_walkthrough("Test Feature", "Execution completed successfully.", ["file1.ts", "file2.ts"])

        # Inject context
        set_bot_context(self.mock_bridge, self.mock_tunnel_mgr, self.mock_dev_mgr, self.plan_mgr)
        self.client = TestClient(app)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_get_index(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("text/html", res.headers["content-type"])
        self.assertIn("Antigravity Mission Control", res.text)

    def test_get_status(self):
        res = self.client.get("/api/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["model"], "gemini-2.5-flash")
        self.assertEqual(data["mode"], "plan")
        self.assertTrue(data["devRunning"])
        self.assertEqual(data["tunnelUrl"], "https://test-tunnel.trycloudflare.com")

    def test_get_active_plan_parses_tasks(self):
        res = self.client.get("/api/plan/active")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("Test Feature", data["title"])
        self.assertEqual(len(data["tasks"]), 2)
        self.assertFalse(data["tasks"][0]["done"])
        self.assertEqual(data["tasks"][0]["file"], "file1.ts")
        self.assertTrue(data["tasks"][1]["done"])
        self.assertEqual(data["tasks"][1]["file"], "file2.ts")

    def test_get_active_walkthrough(self):
        res = self.client.get("/api/plan/walkthrough")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("Completed Tasks & Walkthrough", data["title"])
        self.assertIn("file1.ts", data["files"])

    def test_send_chat_message(self):
        res = self.client.post("/api/chat/send", json={"message": "What port is the dev server on?"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["reply"], "Mocked AI Agent reply")
        self.assertEqual(data["model"], "gemini-2.5-flash")

    def test_get_history(self):
        res = self.client.get("/api/history")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIsInstance(data["history"], list)

    def test_create_new_project(self):
        res = self.client.post(
            "/api/projects/create",
            json={"name": "test-new-app", "template": "html"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["name"], "test-new-app")


if __name__ == "__main__":
    unittest.main()
