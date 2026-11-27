"""Translate Google Workspace add-on events into Aurora's existing Chat handlers."""

import logging
import os

from utils.web.public_url import external_backend_url

logger = logging.getLogger(__name__)


def normalize_chat_event(event: dict) -> dict:
    """Keep classic events intact; map supported add-on payloads without guessing a user."""
    if "chat" not in event:
        return event
    chat = event["chat"]
    if not isinstance(chat, dict):
        raise ValueError("Invalid Chat add-on envelope")
    payload_types = {
        "messagePayload": "MESSAGE",
        "addedToSpacePayload": "ADDED_TO_SPACE",
        "removedFromSpacePayload": "REMOVED_FROM_SPACE",
        "buttonClickedPayload": "CARD_CLICKED",
    }
    present = [key for key in payload_types if key in chat]
    if len(present) > 1:
        raise ValueError("Ambiguous Chat add-on payload")
    if not present:
        logger.info("Ignoring unsupported Google Chat add-on trigger")
        return {}
    key = present[0]
    payload = chat[key]
    common = event.get("commonEventObject", {})
    user = chat.get("user", {})
    if not isinstance(payload, dict) or not isinstance(common, dict) or not isinstance(user, dict):
        raise ValueError("Invalid Chat add-on payload")
    parameters = common.get("parameters", {})
    if not isinstance(parameters, dict) or any(
        not isinstance(k, str) or not isinstance(v, str) for k, v in parameters.items()
    ):
        raise ValueError("Invalid Chat add-on action parameters")
    message = payload.get("message", {})
    space = payload.get("space", {})
    if not isinstance(message, dict) or not isinstance(space, dict):
        raise ValueError("Invalid Chat add-on message or space")
    return {
        "type": payload_types[key],
        "user": user,
        "message": message,
        "space": space,
        "common": common,
        "action": {
            "actionMethodName": parameters.get("aurora_action") or parameters.get("__action_method_name__", ""),
            "parameters": [{"key": k, "value": v} for k, v in parameters.items()],
        },
    }


def chat_card_action(function_name: str, parameters: list[dict]) -> dict:
    """HTTP add-on buttons need an endpoint URL and an explicit action parameter."""
    if not os.getenv("GOOGLE_CHAT_ADDON_SERVICE_ACCOUNT_EMAIL", "").strip():
        return {"function": function_name, "parameters": parameters}
    endpoint = external_backend_url()
    if not endpoint.startswith("https://"):
        logger.error("Google Chat add-on buttons require a public HTTPS backend URL")
        raise ValueError("Set NEXT_PUBLIC_BACKEND_URL to the public HTTPS backend URL")
    return {
        "function": f"{endpoint}/google-chat/events",
        "parameters": [*parameters, {"key": "aurora_action", "value": function_name}],
    }
