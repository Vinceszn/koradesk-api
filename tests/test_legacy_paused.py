import asyncio

from fastapi.testclient import TestClient

from app import main


def test_legacy_button_does_not_change_approval():
    class NoDatabase:
        def get(self, *args):
            raise AssertionError("A disabled button must not read or change an approval")

    asyncio.run(main._handle_button(NoDatabase(), object(), "sender", "approve:order:1"))


def test_legacy_approval_admin_and_messages_are_paused(monkeypatch):
    monkeypatch.setattr(main, "verify_signature", lambda *args: True)
    client = TestClient(main.app)
    result = client.post("/admin/approvals/1/decide", data={"decision": "approved"})
    assert result.status_code == 503
    payload = {"entry": [{"changes": [{"value": {"messages": [{"id": "test"}]}}]}]}
    result = client.post("/webhook/receive", json=payload)
    assert result.status_code == 503
    assert "temporarily disabled" in result.text
