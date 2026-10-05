"""Outbound SMS via Africa's Talking. Without credentials, messages go to the outbox table only."""
import logging

import httpx

from . import config, db

log = logging.getLogger("umujyanama.sms")


def send(phone: str, message: str) -> str:
    if not (config.AT_USERNAME and config.AT_API_KEY):
        db.queue_sms(phone, message, "outbox-only")
        log.info("SMS (not sent, no gateway configured) to %s: %s", phone, message)
        return "outbox-only"
    host = "api.sandbox.africastalking.com" if config.AT_SANDBOX else "api.africastalking.com"
    data = {"username": config.AT_USERNAME, "to": phone, "message": message}
    if config.AT_SENDER_ID:
        data["from"] = config.AT_SENDER_ID
    try:
        r = httpx.post(f"https://{host}/version1/messaging", data=data,
                       headers={"apiKey": config.AT_API_KEY, "Accept": "application/json"}, timeout=10)
        r.raise_for_status()
        status = "sent"
    except httpx.HTTPError as exc:
        log.warning("SMS send failed: %s", exc)
        status = "failed"
    db.queue_sms(phone, message, status)
    return status
