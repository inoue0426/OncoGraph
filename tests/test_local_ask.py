"""Local model bridge rejects cross-origin requests and forwards only bounded records."""

from fastapi.testclient import TestClient

from oncograph import local_ask


def _payload():
    return {"question": "What is recorded for EGFR?", "records": [{
        "id": "R1", "subject": "EGFR", "predicate": "associated_with", "object": "Lung cancer",
        "sources": [{"source": "civic", "claim_state": "contradicts"}],
    }]}


def test_same_origin_only_and_no_remote_model(monkeypatch):
    monkeypatch.setattr(local_ask, "_ask_ollama", lambda packet: "Limited evidence [R1].")
    client = TestClient(local_ask.app, base_url="http://127.0.0.1:8765")
    good = client.post("/api/local-answer", json=_payload(), headers={"Origin": "http://127.0.0.1:8765"})
    assert good.status_code == 200
    assert good.json()["record_count"] == 1
    assert client.post("/api/local-answer", json=_payload(),
                       headers={"Origin": "https://inoue0426.github.io"}).status_code == 403
    assert client.post("/api/local-answer", json=_payload()).status_code == 403
    assert client.post("/api/local-answer", json=_payload(), headers={
        "Origin": "http://evil.example", "Host": "evil.example"}).status_code == 400


def test_rejects_unbounded_or_empty_evidence(monkeypatch):
    monkeypatch.setattr(local_ask, "_ask_ollama", lambda packet: "Should not be called")
    client = TestClient(local_ask.app, base_url="http://127.0.0.1:8765")
    headers = {"Origin": "http://127.0.0.1:8765"}
    assert client.post("/api/local-answer", json={"question": "EGFR?", "records": []},
                       headers=headers).status_code == 422
    huge = {**_payload(), "question": "X" * 30000}
    assert client.post("/api/local-answer", json=huge, headers=headers).status_code == 413
