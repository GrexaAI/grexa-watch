"""Translate Google Workspace add-on events into Aurora's existing Chat handlers."""

import logging
import os
import re

from bs4 import BeautifulSoup

from utils.web.public_url import external_backend_url

logger = logging.getLogger(__name__)


def extract_message_text(message: dict, max_length: int = 50000) -> str:
    """Read visible text and HTTP links from messages and legacy/v2 alert cards.

    Card actions, parameters and form values are deliberately excluded. Returned
    content is conversation data, never an instruction to execute a card action.
    """
    parts = []
    remaining = max(max_length, 0)
    nodes_left = 1000

    def add(value):
        nonlocal remaining
        if not isinstance(value, str) or remaining <= 0:
            return
        value = value[:remaining]
        if re.search(r"</?[A-Za-z][^>]*>", value):
            soup = BeautifulSoup(value, "html.parser")
            for tag in soup(["script", "style"]):
                tag.decompose()
            for anchor in soup.find_all("a", href=True):
                url = anchor["href"]
                if url.lower().startswith(("http://", "https://")):
                    anchor.replace_with(f"{anchor.get_text()} ({url})")
            for br in soup.find_all("br"):
                br.replace_with("\n")
            value = soup.get_text()
        value = value.strip()[:remaining]
        if value:
            parts.append(value)
            remaining -= len(value) + 1

    def walk(node, depth=0):
        nonlocal nodes_left
        if depth > 16 or nodes_left <= 0 or remaining <= 0:
            return
        nodes_left -= 1
        if isinstance(node, list):
            for item in node:
                walk(item, depth + 1)
        elif isinstance(node, dict):
            for key, value in node.items():
                if key in ("title", "subtitle", "text", "topLabel", "bottomLabel", "content", "altText"):
                    add(value)
                elif key == "openLink" and isinstance(value, dict):
                    url = value.get("url")
                    if isinstance(url, str) and url.lower().startswith(("http://", "https://")):
                        add(url)
                elif key in (
                    "header", "sections", "widgets", "textParagraph", "decoratedText",
                    "keyValue", "buttons", "buttonList", "textButton", "onClick",
                    "fixedFooter", "primaryButton", "secondaryButton", "columns",
                    "columnItems", "uncollapsibleWidgets",
                ):
                    walk(value, depth + 1)

    add(message.get("text") or message.get("formattedText"))
    walk(message.get("cards", []))
    cards_v2 = message.get("cardsV2", [])
    if isinstance(cards_v2, list):
        for entry in cards_v2:
            if isinstance(entry, dict):
                walk(entry.get("card"))
    if not parts:
        add(message.get("fallbackText"))
    return "\n".join(parts)[:max(max_length, 0)]


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
