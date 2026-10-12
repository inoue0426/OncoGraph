"""The removed public bridge cannot be re-enabled by old environment settings."""

import os
import subprocess
import sys


def test_old_public_mode_flag_does_not_expose_bridge():
    code = '''
from fastapi.testclient import TestClient
from oncograph import local_ask

local_ask._ask_ollama = lambda packet: "Research-only [R1]."
client = TestClient(local_ask.app, base_url="https://demo.trycloudflare.com")
payload = {"question": "What evidence mentions EGFR?", "records": [{
    "id": "R1", "subject": "EGFR", "predicate": "associated_with", "object": "Disease",
    "sources": [{"source": "civic", "claim_state": "supports"}],
}]}
headers = {"Origin": "https://demo.trycloudflare.com", "CF-Connecting-IP": "203.0.113.1"}
assert client.get("/").status_code == 400
assert client.post("/api/local-answer", json=payload, headers=headers).status_code == 400
assert TestClient(local_ask.app, base_url="http://127.0.0.1:8765").get(
    "/api/local-answer/status").json()["mode"] == "local_only"
'''
    env = {**os.environ, "ONCOGRAPH_PUBLIC_MODE": "1",
           "ONCOGRAPH_PUBLIC_HOST": "demo.trycloudflare.com"}
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True,
                            text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
