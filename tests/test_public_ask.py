"""A public quick tunnel needs origin checks, Cloudflare IP and a small budget."""

import os
import subprocess
import sys


def test_bounded_public_bridge_is_opt_in():
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
assert client.get("/api/local-answer/status").json()["mode"] == "public_bounded"
assert client.post("/api/local-answer", json=payload, headers={"Origin": headers["Origin"]}).status_code == 403
assert client.post("/api/local-answer", json=payload, headers={**headers, "Origin": "https://evil.example"}).status_code == 403
assert client.post("/api/local-answer", json=payload, headers={**headers, "CF-Connecting-IP": "invalid"}).status_code == 403
for _ in range(3):
    assert client.post("/api/local-answer", json=payload, headers=headers).status_code == 200
assert client.post("/api/local-answer", json=payload, headers=headers).status_code == 429
assert TestClient(local_ask.app, base_url="https://evil.example").get("/").status_code == 400
'''
    env = {**os.environ, "ONCOGRAPH_PUBLIC_MODE": "1"}
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True,
                            text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
