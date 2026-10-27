"""Thin async client for the Meta WhatsApp Cloud API (direct, no BSP)."""

import httpx

from app.config import settings


def _url() -> str:
    return (
        f"https://graph.facebook.com/{settings.graph_version}/"
        f"{settings.whatsapp_phone_number_id}/messages"
    )


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.whatsapp_token}",
        "Content-Type": "application/json",
    }


async def send_text(to: str, body: str, preview_url: bool = False) -> dict:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            _url(),
            headers=_headers(),
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": body, "preview_url": preview_url},
            },
        )
        response.raise_for_status()
        return response.json()


async def send_approval(to: str, header: str, body: str, approve_id: str, reject_id: str) -> dict:
    """Interactive Approve/Reject buttons. Payloads echo back as button replies."""
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            _url(),
            headers=_headers(),
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "header": {"type": "text", "text": header[:60]},
                    "body": {"text": body[:1024]},
                    "action": {
                        "buttons": [
                            {
                                "type": "reply",
                                "reply": {"id": approve_id[:256], "title": "Approve"},
                            },
                            {"type": "reply", "reply": {"id": reject_id[:256], "title": "Reject"}},
                        ]
                    },
                },
            },
        )
        response.raise_for_status()
        return response.json()


async def mark_read(message_id: str) -> None:
    async with httpx.AsyncClient(timeout=20) as client:
        await client.post(
            _url(),
            headers=_headers(),
            json={
                "messaging_product": "whatsapp",
                "status": "read",
                "message_id": message_id,
            },
        )


async def download_media(media_id: str) -> bytes:
    """Two-step fetch: metadata URL first (needs auth), then bytes."""
    async with httpx.AsyncClient(timeout=30) as client:
        meta = await client.get(
            f"https://graph.facebook.com/{settings.graph_version}/{media_id}",
            headers=_headers(),
        )
        meta.raise_for_status()
        file_response = await client.get(
            meta.json()["url"], headers=_headers(), follow_redirects=True
        )
        file_response.raise_for_status()
        return file_response.content
