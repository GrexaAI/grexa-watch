"""Alert cards and old thread roots must reach the investigation context."""

from unittest.mock import MagicMock

import pytest
import requests

from connectors.google_chat_connector.client import GoogleChatClient
from connectors.google_chat_connector.events import extract_message_text
from routes.google_chat.google_chat_events_helpers import get_space_context_with_threads, get_thread_messages

SPACE = "spaces/test-space"
THREAD = f"{SPACE}/threads/old-thread"
ALERT_URL = "https://mon.grexa.ai/alerting/list"


@pytest.fixture
def card():
    return {
        "header": {"title": "RMQ - High Error Rate", "subtitle": "Production"},
        "sections": [{"widgets": [
            {"textParagraph": {"text": "<b>Active Alerts: 2</b><br>campaignSummaryDailySync — 100.00%\n"
                                       "gbpDailyPerformanceSync — 5.77%"}},
            {"buttons": [{"textButton": {
                "text": "OPEN IN GRAFANA", "onClick": {"openLink": {"url": ALERT_URL}},
            }}]},
        ]}],
    }


@pytest.mark.parametrize("version", ["cards", "cardsV2"])
def test_reads_grafana_card_text_and_button_link(card, version):
    message = {"text": "[FIRING:2, RESOLVED:1] RMQ"}
    message[version] = [card] if version == "cards" else [{"cardId": "alert", "card": card}]
    text = extract_message_text(message)
    for expected in ("[FIRING:2, RESOLVED:1]", "RMQ - High Error Rate", "Active Alerts: 2",
                     "campaignSummaryDailySync — 100.00%", "gbpDailyPerformanceSync — 5.77%", ALERT_URL):
        assert expected in text
    assert "<b>" not in text
    assert "2\ncampaignSummary" in text


def test_v2_widgets_preserve_visible_links_without_action_parameters():
    text = extract_message_text({"cardsV2": [{"card": {"sections": [{"widgets": [
        {"decoratedText": {"topLabel": "Severity", "text": "critical", "bottomLabel": "prod"}},
        {"textParagraph": {"text": '<a href="https://mon.grexa.ai/a?a=1&amp;b=2">View alert</a>'}},
        {"buttonList": {"buttons": [{"text": "Run", "onClick": {"action": {
            "function": "hidden-handler", "parameters": [{"key": "secret", "value": "hidden-value"}],
        }}}]}},
    ]}]}}]})
    assert "Severity\ncritical\nprod" in text
    assert "View alert (https://mon.grexa.ai/a?a=1&b=2)" in text
    assert "hidden" not in text


@pytest.mark.parametrize("message", [
    {"cards": None, "cardsV2": [None, {"card": None}]},
    {"cards": [{"sections": "bad"}], "cardsV2": {}},
])
def test_malformed_cards_do_not_hide_plain_text(message):
    assert extract_message_text({"text": "Alert", **message}) == "Alert"


def test_card_only_fallback_limits_and_non_http_links(card):
    assert "Active Alerts: 2" in extract_message_text({"cards": [card]})
    assert extract_message_text({"fallbackText": "Fallback"}) == "Fallback"
    assert len(extract_message_text({"cards": [card]}, max_length=30)) <= 30
    assert extract_message_text({"text": "hello"}, max_length=0) == ""
    assert extract_message_text({"cards": [{"onClick": {"openLink": {"url": "javascript:bad()"}}}]}) == ""


def test_client_filters_history_at_google():
    client = GoogleChatClient("test-token")
    client._request = MagicMock(return_value={"messages": [{"name": "message"}]})
    assert client.list_messages(SPACE, page_size=1, order_by="createTime asc", thread_name=THREAD)
    client._request.assert_called_once_with("GET", f"{SPACE}/messages", params={
        "pageSize": 1, "orderBy": "createTime asc", "filter": f"thread.name = {THREAD}",
    })


@pytest.mark.parametrize("thread", ["spaces/other/threads/1", THREAD + ' OR createTime > "2020"', "old-thread"])
def test_client_rejects_cross_space_or_invalid_thread(thread):
    client = GoogleChatClient("test-token")
    client._request = MagicMock()
    with pytest.raises(ValueError):
        client.list_messages(SPACE, thread_name=thread)
    client._request.assert_not_called()


def message(name, timestamp, text="", **kwargs):
    return {"name": name, "createTime": timestamp, "text": text,
            "thread": {"name": THREAD}, "sender": {"displayName": "grafana", "type": "BOT"}, **kwargs}


def test_old_alert_root_and_recent_replies_are_returned_in_order(card):
    root = message("root", "2026-11-25T08:09:00Z", cards=[card])
    client = MagicMock()
    client.list_messages.side_effect = [[root], [
        message("reply-2", "2026-11-27T09:00:00Z", "check this"),
        message("reply-1", "2026-11-27T08:00:00Z", "earlier reply"),
        root,
        message("unrelated", "2026-11-26T08:00:00Z", "unrelated", thread={"name": THREAD + "-other"}),
    ]]
    context = get_thread_messages(client, SPACE, THREAD)
    assert [m["text"] for m in context][1:] == ["earlier reply", "check this"]
    assert ALERT_URL in context[0]["text"]
    assert context[0]["display_name"] == "grafana"
    assert len(context) == 3
    assert client.list_messages.call_args_list[0].kwargs == {
        "page_size": 1, "order_by": "createTime asc", "thread_name": THREAD,
    }
    assert client.list_messages.call_args_list[1].kwargs == {
        "page_size": 9, "order_by": "createTime desc", "thread_name": THREAD,
    }


def test_context_limits_keep_root_first(card):
    client = MagicMock()
    client.list_messages.side_effect = [[message("root", "1", cards=[card])], [message("reply", "2", "x" * 100)]]
    context = get_thread_messages(client, SPACE, THREAD, max_message_length=50, max_total_length=100)
    assert len(context) == 1
    assert "RMQ" in context[0]["text"]
    assert "truncated" in context[0]["text"]


def test_recent_space_context_includes_card_only_message(card):
    client = MagicMock()
    client.list_messages.return_value = [message("root", "2026-11-27T08:09:00Z", cards=[card])]
    context = get_space_context_with_threads(client, SPACE)
    assert "grafana:" in context
    assert "RMQ - High Error Rate" in context


def test_denied_history_falls_back_without_context():
    client = MagicMock()
    response = requests.Response()
    response.status_code = 403
    client.list_messages.side_effect = requests.HTTPError(response=response)
    assert get_thread_messages(client, SPACE, THREAD) == []
