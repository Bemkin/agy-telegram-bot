"""
test_server_api.py — Integration tests for FastAPI Mission Control endpoints.
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

import json
import time

from config import Config
from plan_manager import PlanManager
from server import app, set_bot_context
from webapp_auth import INIT_DATA_HEADER, sign_init_data

TEST_TOKEN = "123456:TEST-TOKEN"
OWNER_ID = 4242


def owner_init_data(user_id=OWNER_ID, token=TEST_TOKEN, auth_date=None):
    fields = {
        "auth_date": str(int(time.time()) if auth_date is None else auth_date),
        "query_id": "AAH-test",
        "user": json.dumps({"id": user_id, "first_name": "Owner"}, separators=(",", ":")),
    }
    return sign_init_data(fields, token)


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
        self._orig = (Config.TELEGRAM_BOT_TOKEN, Config.AUTHORIZED_USER_ID)
        Config.TELEGRAM_BOT_TOKEN, Config.AUTHORIZED_USER_ID = TEST_TOKEN, OWNER_ID
        self.anon = TestClient(app)
        self.client = TestClient(app, headers={INIT_DATA_HEADER: owner_init_data()})

    def tearDown(self):
        Config.TELEGRAM_BOT_TOKEN, Config.AUTHORIZED_USER_ID = self._orig
        shutil.rmtree(self.test_dir, ignore_errors=True)

    # ── Mini App auth ──────────────────────────────────────────────
    def test_api_rejects_missing_init_data(self):
        for method, path in [("get", "/api/status"), ("post", "/api/git/push"), ("post", "/api/plan/approve"), ("get", "/api/preview/image")]:
            res = getattr(self.anon, method)(path)
            self.assertEqual(res.status_code, 401, path)

    def test_api_rejects_forged_signature(self):
        res = self.anon.get("/api/status", headers={INIT_DATA_HEADER: owner_init_data(token="999:WRONG")})
        self.assertEqual(res.status_code, 401)

    def test_api_rejects_other_user(self):
        res = self.anon.get("/api/status", headers={INIT_DATA_HEADER: owner_init_data(user_id=1)})
        self.assertEqual(res.status_code, 401)

    def test_api_rejects_expired_init_data(self):
        stale = int(time.time()) - 2 * 24 * 60 * 60
        res = self.anon.get("/api/status", headers={INIT_DATA_HEADER: owner_init_data(auth_date=stale)})
        self.assertEqual(res.status_code, 401)

    def test_api_rejects_tampered_fields(self):
        signed = owner_init_data()
        tampered = signed.replace("Owner", "Mallory")
        res = self.anon.get("/api/status", headers={INIT_DATA_HEADER: tampered})
        self.assertEqual(res.status_code, 401)

    def test_index_stays_public(self):
        self.assertEqual(self.anon.get("/").status_code, 200)

    def test_no_wildcard_cors(self):
        res = self.client.get("/api/status", headers={"Origin": "https://evil.example"})
        self.assertNotIn("access-control-allow-origin", {k.lower() for k in res.headers})

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
