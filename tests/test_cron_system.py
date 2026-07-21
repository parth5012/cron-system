import os
import sys
import unittest
from pathlib import Path

# Put cron-system on python path
cron_system_dir = Path(__file__).parent.parent
sys.path.insert(0, str(cron_system_dir))

os.environ["CRON_SECRET"] = "test-secret-123"

from main import app
from cron_engine import CronEngine, get_engine, RunRecord
from fastapi.testclient import TestClient

client = TestClient(app)

class TestCronSystem(unittest.TestCase):
    def test_health(self):
        response = client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_cron_dispatch_unauthorized(self):
        response = client.get("/cron/warmup")
        self.assertEqual(response.status_code, 401)

        response = client.get("/cron/warmup", headers={"X-Cron-Secret": "wrong-secret"})
        self.assertEqual(response.status_code, 401)

    def test_cron_dispatch_not_found(self):
        response = client.get("/cron/nonexistent", headers={"X-Cron-Secret": "test-secret-123"})
        self.assertEqual(response.status_code, 404)

    def test_cron_dispatch_success(self):
        response = client.get("/cron/warmup", headers={"X-Cron-Secret": "test-secret-123"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["job"], "warmup")
        self.assertIn("status", data)
        self.assertIn("exit_code", data)
        self.assertIn("duration_ms", data)

    def test_cron_manual_run(self):
        response = client.post("/cron/warmup/run", headers={"X-Cron-Secret": "test-secret-123"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["job"], "warmup")

    def test_cron_logs(self):
        client.get("/cron/warmup", headers={"X-Cron-Secret": "test-secret-123"})

        response = client.get("/cron/warmup/log", headers={"X-Cron-Secret": "test-secret-123"})
        self.assertEqual(response.status_code, 200)
        logs = response.json()
        self.assertIsInstance(logs, list)
        self.assertGreater(len(logs), 0)
        self.assertEqual(logs[0]["job"], "warmup")

    def test_background_job(self):
        response = client.get("/cron/backup", headers={"X-Cron-Secret": "test-secret-123"})
        self.assertEqual(response.status_code, 202)
        data = response.json()
        self.assertEqual(data["job"], "backup")
        self.assertEqual(data["status"], "accepted")

if __name__ == "__main__":
    unittest.main()