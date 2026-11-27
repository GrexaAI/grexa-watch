"""Classic and Workspace add-on events share Aurora's existing authorization paths."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from flask import Flask, jsonify

from connectors.google_chat_connector.events import chat_card_action, normalize_chat_event

ADDON_SENDER = "service-123456789@gcp-sa-gsuiteaddons.iam.gserviceaccount.com"
EVENT_URL = "https://watch.example.com/google-chat/events"


def addon_event(payload="messagePayload"):
    return {
        "chat": {
            "user": {"name": "users/123", "email": "sender@example.com"},
            payload: {
                "space": {"name": "spaces/space-1", "spaceType": "SPACE"},
                "message": {
                    "name": "spaces/space-1/messages/1",
                    "argumentText": "Check unhealthy pods",
                    "thread": {"name": "spaces/space-1/threads/1"},
                },
            },
        },
    }


@pytest.mark.parametrize("payload,event_type", [
    ("messagePayload", "MESSAGE"), ("addedToSpacePayload", "ADDED_TO_SPACE"),
    ("removedFromSpacePayload", "REMOVED_FROM_SPACE"), ("buttonClickedPayload", "CARD_CLICKED"),
])
def test_normalize_supported_payloads(payload, event_type):
    data = normalize_chat_event(addon_event(payload))
    assert data["type"] == event_type
    assert data["user"]["email"] == "sender@example.com"
    assert data["space"]["name"] == "spaces/space-1"
    assert data["message"]["thread"]["name"] == "spaces/space-1/threads/1"


def test_addon_sender_never_falls_back_to_legacy_user():
    event = addon_event()
    event["user"] = {"email": "admin@example.com"}
    del event["chat"]["user"]
    assert normalize_chat_event(event)["user"] == {}


@pytest.mark.parametrize("key", ["aurora_action", "__action_method_name__"])
def test_button_method_and_parameters(key):
    event = addon_event("buttonClickedPayload")
    event["commonEventObject"] = {"parameters": {key: "run_suggestion", "incident_id": "incident-1"}}
    action = normalize_chat_event(event)["action"]
    assert action["actionMethodName"] == "run_suggestion"
    assert {p["key"]: p["value"] for p in action["parameters"]}["incident_id"] == "incident-1"


@pytest.mark.parametrize("event", [
    {"chat": []}, {"chat": {"messagePayload": []}},
    {"chat": {"messagePayload": {}, "addedToSpacePayload": {}}},
    {"chat": {"messagePayload": {"message": []}}},
    {"chat": {"messagePayload": {}, "user": []}},
    {"chat": {"messagePayload": {}}, "commonEventObject": {"parameters": []}},
    {"chat": {"messagePayload": {}}, "commonEventObject": {"parameters": {"method": {}}}},
])
def test_reject_invalid_addon_payload(event):
    with pytest.raises(ValueError):
        normalize_chat_event(event)


def test_classic_payload_is_preserved():
    event = {"type": "MESSAGE", "user": {"email": "sender@example.com"}}
    assert normalize_chat_event(event) is event


def test_unsupported_trigger_does_not_become_a_message():
    assert normalize_chat_event({"chat": {"appCommandPayload": {"message": {"text": "run"}}}}) == {}


@pytest.fixture
def verifier(monkeypatch):
    from routes.google_chat import google_chat_events_helpers as helpers
    monkeypatch.setenv("NEXT_PUBLIC_BACKEND_URL", "https://watch.example.com")
    monkeypatch.delenv("GOOGLE_CHAT_ADDON_SERVICE_ACCOUNT_EMAIL", raising=False)
    claims = {"email": ADDON_SENDER, "email_verified": True}
    verify = MagicMock(side_effect=lambda *a, **kw: claims)
    monkeypatch.setattr(helpers, "id_token", SimpleNamespace(verify_oauth2_token=verify))
    app = Flask(__name__)
    return SimpleNamespace(helpers=helpers, claims=claims, verify=verify, app=app)


def test_addon_verifies_signature_audience_and_exact_identity(verifier, monkeypatch):
    monkeypatch.setenv("GOOGLE_CHAT_ADDON_SERVICE_ACCOUNT_EMAIL", ADDON_SENDER)
    with verifier.app.test_request_context(headers={"Authorization": "Bearer test-token"}):
        assert verifier.helpers.verify_google_chat_request(addon_event())
    assert verifier.verify.call_args.args[0] == "test-token"
    assert verifier.verify.call_args.kwargs == {"audience": EVENT_URL}


@pytest.mark.parametrize("email,verified", [
    ("service-999@gcp-sa-gsuiteaddons.iam.gserviceaccount.com", True),
    ("chat@system.gserviceaccount.com", True),
    ("sender@example.com", True), (ADDON_SENDER, False), (ADDON_SENDER, None),
])
def test_addon_rejects_wrong_or_unverified_sender(verifier, monkeypatch, email, verified):
    monkeypatch.setenv("GOOGLE_CHAT_ADDON_SERVICE_ACCOUNT_EMAIL", ADDON_SENDER)
    verifier.claims.update(email=email, email_verified=verified)
    with verifier.app.test_request_context(headers={"Authorization": "Bearer test-token"}):
        assert not verifier.helpers.verify_google_chat_request(addon_event())


def test_classic_signer_remains_supported(verifier):
    verifier.claims["email"] = "chat@system.gserviceaccount.com"
    with verifier.app.test_request_context(headers={"Authorization": "Bearer test-token"}):
        assert verifier.helpers.verify_google_chat_request({"type": "MESSAGE"})


def test_addon_without_config_fails_closed(verifier):
    with verifier.app.test_request_context(headers={"Authorization": "Bearer test-token"}):
        assert not verifier.helpers.verify_google_chat_request(addon_event())
    verifier.verify.assert_not_called()


def test_invalid_config_is_not_an_arbitrary_signer_allowlist(verifier, monkeypatch):
    monkeypatch.setenv("GOOGLE_CHAT_ADDON_SERVICE_ACCOUNT_EMAIL", "user@example.com")
    with verifier.app.test_request_context(headers={"Authorization": "Bearer test-token"}):
        assert not verifier.helpers.verify_google_chat_request(addon_event())
    verifier.verify.assert_not_called()


def test_invalid_signature_or_audience_is_rejected_without_logging_token(verifier, monkeypatch, caplog):
    monkeypatch.setenv("GOOGLE_CHAT_ADDON_SERVICE_ACCOUNT_EMAIL", ADDON_SENDER)
    verifier.verify.side_effect = ValueError("test-token")
    with verifier.app.test_request_context(headers={"Authorization": "Bearer test-token"}):
        assert not verifier.helpers.verify_google_chat_request(addon_event())
    assert "test-token" not in caplog.text


def test_missing_bearer_is_rejected(verifier):
    with verifier.app.test_request_context():
        assert not verifier.helpers.verify_google_chat_request({"type": "MESSAGE"})
    verifier.verify.assert_not_called()


@pytest.fixture
def route(monkeypatch):
    # Background dispatch is mocked: no broker, database, messages, or cloud calls.
    monkeypatch.setitem(sys.modules, "chat.background.task", SimpleNamespace(run_background_chat=MagicMock()))
    filename = Path(__file__).parents[2] / "routes/google_chat/google_chat_events.py"
    spec = importlib.util.spec_from_file_location("_test_chat_addon_route", filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "verify_google_chat_request", lambda _: True)
    monkeypatch.setattr(module, "get_org_google_chat_credentials", lambda _: ("owner", "org", "sender-user"))
    monkeypatch.setattr(module, "_user_can_execute", lambda _: True)
    client = MagicMock()
    client.send_message.return_value = {"name": "spaces/space-1/messages/thinking"}
    monkeypatch.setattr(module, "get_chat_app_client", lambda: client)
    monkeypatch.setattr(module, "get_session_from_thread", lambda *a: ("session-1", None))
    monkeypatch.setattr(module, "get_thread_messages", lambda *a: [])
    dispatch = MagicMock()
    monkeypatch.setattr(module, "send_message_to_aurora", dispatch)
    app = Flask(__name__)
    app.register_blueprint(module.google_chat_events_bp, url_prefix="/google-chat")
    return SimpleNamespace(module=module, http=app.test_client(), client=client, dispatch=dispatch)


def test_addon_message_uses_existing_sender_and_thread_authorization(route):
    response = route.http.post("/google-chat/events", json=addon_event())
    assert response.status_code == 200
    assert response.json == {}
    assert route.dispatch.call_args.kwargs["user_id"] == "sender-user"
    assert route.dispatch.call_args.kwargs["session_id"] == "session-1"
    assert route.dispatch.call_args.kwargs["message_text"] == "Check unhealthy pods"


def test_addon_role_denial_never_dispatches(route, monkeypatch):
    monkeypatch.setattr(route.module, "_user_can_execute", lambda _: False)
    assert route.http.post("/google-chat/events", json=addon_event()).status_code == 200
    route.dispatch.assert_not_called()
    assert "permission" in route.client.send_message.call_args.kwargs["text"]


def test_addon_button_role_denial_never_enqueues_command(route, monkeypatch):
    event = addon_event("buttonClickedPayload")
    event["commonEventObject"] = {"parameters": {
        "aurora_action": "run_suggestion", "incident_id": "incident-1", "suggestion_id": "suggestion-1",
    }}
    monkeypatch.setattr(route.module, "_user_can_execute", lambda _: False)
    response = route.http.post("/google-chat/events", json=event)
    assert response.status_code == 200
    assert response.json == {}
    route.module.run_background_chat.delay.assert_not_called()
    route.client.send_private_message.assert_called_once()


def test_unknown_addon_sender_never_dispatches(route, monkeypatch):
    monkeypatch.setattr(route.module, "get_org_google_chat_credentials", lambda _: None)
    route.http.post("/google-chat/events", json=addon_event())
    route.dispatch.assert_not_called()


def test_failed_verification_stops_before_handlers(route, monkeypatch):
    monkeypatch.setattr(route.module, "verify_google_chat_request", lambda _: False)
    assert route.http.post("/google-chat/events", json=addon_event()).status_code == 403
    route.dispatch.assert_not_called()
    route.client.send_message.assert_not_called()


def test_addon_welcome_has_render_actions_envelope(route):
    response = route.http.post("/google-chat/events", json=addon_event("addedToSpacePayload"))
    assert response.status_code == 200
    text = response.json["hostAppDataAction"]["chatDataAction"]["createMessageAction"]["message"]["text"]
    assert "Thanks for adding me" in text


def test_classic_welcome_keeps_message_response(route):
    response = route.http.post("/google-chat/events", json={"type": "ADDED_TO_SPACE", "space": {"spaceType": "SPACE"}})
    assert "Thanks for adding me" in response.json["text"]


def test_addon_button_reuses_handler_and_wraps_text_response(route, monkeypatch):
    event = addon_event("buttonClickedPayload")
    event["commonEventObject"] = {"parameters": {"aurora_action": "run_suggestion", "incident_id": "incident-1", "suggestion_id": "suggestion-1"}}
    run = MagicMock(side_effect=lambda **kw: (jsonify({"text": "Executing"}), 200))
    monkeypatch.setattr(route.module, "_handle_run_suggestion", run)
    response = route.http.post("/google-chat/events", json=event)
    assert run.call_args.kwargs["sender_user_id"] == "sender-user"
    assert run.call_args.kwargs["parameters"]["suggestion_id"] == "suggestion-1"
    assert response.json["hostAppDataAction"]["chatDataAction"]["createMessageAction"]["message"]["text"] == "Executing"


def test_unsupported_trigger_acknowledged_without_dispatch(route):
    response = route.http.post("/google-chat/events", json={"chat": {"appCommandPayload": {}}})
    assert response.json == {}
    route.dispatch.assert_not_called()


def test_ambiguous_trigger_is_rejected(route):
    event = addon_event()
    event["chat"]["buttonClickedPayload"] = {}
    assert route.http.post("/google-chat/events", json=event).status_code == 400
    route.dispatch.assert_not_called()


def test_non_object_event_is_rejected(route):
    assert route.http.post("/google-chat/events", json=[]).status_code == 400


def test_addon_buttons_use_https_endpoint_without_mutating_parameters(monkeypatch):
    monkeypatch.setenv("NEXT_PUBLIC_BACKEND_URL", "https://watch.example.com/")
    monkeypatch.setenv("GOOGLE_CHAT_ADDON_SERVICE_ACCOUNT_EMAIL", ADDON_SENDER)
    parameters = [{"key": "incident_id", "value": "incident-1"}]
    action = chat_card_action("run_suggestion", parameters)
    assert action["function"] == EVENT_URL
    assert action["parameters"][-1] == {"key": "aurora_action", "value": "run_suggestion"}
    assert parameters == [{"key": "incident_id", "value": "incident-1"}]


def test_classic_buttons_remain_named_functions(monkeypatch):
    monkeypatch.delenv("GOOGLE_CHAT_ADDON_SERVICE_ACCOUNT_EMAIL", raising=False)
    assert chat_card_action("suggestion_details", []) == {"function": "suggestion_details", "parameters": []}


def test_addon_buttons_reject_private_http_backend(monkeypatch):
    monkeypatch.setenv("NEXT_PUBLIC_BACKEND_URL", "http://10.0.0.1:5080")
    monkeypatch.setenv("GOOGLE_CHAT_ADDON_SERVICE_ACCOUNT_EMAIL", ADDON_SENDER)
    with pytest.raises(ValueError, match="public HTTPS"):
        chat_card_action("run_suggestion", [])


@pytest.mark.parametrize("addon", [False, True])
def test_rendered_suggestion_cards_match_deployment_mode(monkeypatch, addon):
    from routes.google_chat.google_chat_events_helpers import build_suggestion_cards
    monkeypatch.setenv("NEXT_PUBLIC_BACKEND_URL", "https://watch.example.com")
    monkeypatch.setenv("GOOGLE_CHAT_ADDON_SERVICE_ACCOUNT_EMAIL", ADDON_SENDER if addon else "")
    cards = build_suggestion_cards("incident-1", [{"id": "suggestion-1", "title": "Check pods", "command": "kubectl get pods"}])
    buttons = cards[0]["widgets"][1]["buttonList"]["buttons"]
    for button, method in zip(buttons, ["run_suggestion", "suggestion_details"]):
        action = button["onClick"]["action"]
        assert action["function"] == (EVENT_URL if addon else method)
        params = {p["key"]: p["value"] for p in action["parameters"]}
        assert params["suggestion_id"] == "suggestion-1"
        if addon:
            assert params["aurora_action"] == method
