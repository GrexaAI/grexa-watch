"""Google Chat replies link to the session containing the full investigation."""

import sys
import types
from unittest.mock import MagicMock

import pytest


@pytest.mark.parametrize("has_placeholder", [True, False])
@pytest.mark.parametrize("answer", ["Investigation complete.", "Logs:\n```\n" + "x" * 40000])
def test_google_chat_reply_keeps_session_link(monkeypatch, has_placeholder, answer):
    import utils.cache.redis_client as redis_client

    if redis_client.get_redis_client() is None:
        monkeypatch.setattr(redis_client, "get_redis_client", lambda: MagicMock())

    import chat.background.task as task

    helpers = types.ModuleType("routes.google_chat.google_chat_events_helpers")
    helpers.format_response_for_google_chat = lambda text: text[:3900]
    monkeypatch.setitem(sys.modules, "routes.google_chat.google_chat_events_helpers", helpers)
    monkeypatch.setenv("FRONTEND_URL", "https://watch.grexa.ai/")
    monkeypatch.setattr(task, "_last_saved_assistant_text", lambda *args: answer)
    client = MagicMock()
    monkeypatch.setattr(task, "get_chat_app_client", lambda: client)
    metadata = {"source": "google_chat", "space_name": "spaces/test", "thread_key": "spaces/test/threads/1"}
    if has_placeholder:
        metadata["thinking_message_name"] = "spaces/test/messages/1"

    assert task._send_response_to_google_chat("user-1", "session-1", metadata)

    client.update_message.assert_not_called()
    client.send_message.assert_called_once()
    assert client.send_message.call_args.kwargs["thread_key"] == metadata["thread_key"]
    text = client.send_message.call_args.kwargs["text"]
    assert text.endswith(
        "<https://watch.grexa.ai/chat?sessionId=session-1|Open the full investigation in Watch>"
    )
    assert text.count("```") % 2 == 0
