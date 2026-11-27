"""Code drafting uses Sol without changing the investigator or publishing code."""

import json
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage

from chat.backend.agent.tools import generate_code_tool as coding
from chat.backend.agent.llm import LLMManager, ModelConfig
from chat.backend.agent.model_mapper import ModelMapper
from chat.backend.agent.utils.llm_usage_tracker import LLMUsageTracker


@pytest.fixture
def manager(monkeypatch):
    factory = MagicMock()
    factory.return_value.invoke.return_value = {"messages": [AIMessage(content="--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-old\n+new")]}
    monkeypatch.setattr(coding, "LLMManager", factory)
    monkeypatch.setattr(ModelConfig, "CODING_MODEL", "openai/gpt-6.1-sol")
    monkeypatch.delenv("CODING_REASONING_EFFORT", raising=False)
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "low")
    return factory


def test_drafts_with_sol_medium_and_tracks_same_session(manager, monkeypatch):
    result = json.loads(coding.generate_code("Fix race", "app.py: old", user_id="u1", session_id="s1"))
    assert result["success"] and result["model"] == "openai/gpt-6.1-sol"
    assert result["applied"] is False and result["tests_run"] is False
    assert "+new" in result["proposal"]
    manager.assert_called_once_with(
        main_model="openai/gpt-6.1-sol", vision_model="openai/gpt-6.1-sol", provider_mode="openai",
        model_kwargs={"reasoning": {"effort": "medium", "summary": "auto"}, "max_tokens": 12000},
    )
    call = manager.return_value.invoke.call_args
    assert call.kwargs == {"user_id": "u1", "session_id": "s1", "request_type": "code_generation"}
    assert json.loads(call.args[0][1].content) == {"task": "Fix race", "source_context": "app.py: old"}
    assert "no tools" in call.args[0][0].content
    import os
    assert os.environ["OPENAI_REASONING_EFFORT"] == "low"


@pytest.mark.parametrize("task,context,user,session", [
    ("", "code", "u", "s"), ("x" * 8001, "code", "u", "s"),
    ("fix", "", "u", "s"), ("fix", "x" * 60001, "u", "s"),
    ("fix", "code", None, "s"), ("fix", "code", "u", None),
    ("  ", "code", "u", "s"), ("fix", "\n  ", "u", "s"),
])
def test_invalid_context_never_calls_paid_model(manager, task, context, user, session):
    result = json.loads(coding.generate_code(task, context, user_id=user, session_id=session))
    assert result["success"] is False
    manager.assert_not_called()


def test_effort_override_is_local_to_coding(manager, monkeypatch):
    monkeypatch.setenv("CODING_REASONING_EFFORT", "high")
    coding.generate_code("Fix race", "code", user_id="u", session_id="s")
    assert manager.call_args.kwargs["model_kwargs"]["reasoning"]["effort"] == "high"


def test_invalid_configuration_never_falls_back(manager, monkeypatch):
    monkeypatch.setenv("CODING_REASONING_EFFORT", "none")
    assert not json.loads(coding.generate_code("Fix", "code", user_id="u", session_id="s"))["success"]
    manager.assert_not_called()


def test_model_failure_is_reported_without_credential_or_source_leak(manager, caplog):
    manager.return_value.invoke.side_effect = RuntimeError("private-token-and-source")
    result = coding.generate_code("Fix", "code", user_id="u", session_id="s")
    assert json.loads(result)["success"] is False
    assert "private-token-and-source" not in result + caplog.text
    manager.assert_called_once()


def test_empty_generation_and_reasoning_only_output_are_not_proposals(manager):
    manager.return_value.invoke.return_value = {"messages": [AIMessage(content=[{"type": "reasoning", "summary": []}])]}
    assert not json.loads(coding.generate_code("Fix", "code", user_id="u", session_id="s"))["success"]


@pytest.mark.parametrize("metadata", [{"finish_reason": "length"}, {"status": "incomplete"}, {"incomplete_details": {"reason": "max_output_tokens"}}])
def test_truncated_code_is_not_returned_as_an_applicable_patch(manager, metadata):
    manager.return_value.invoke.return_value = {"messages": [AIMessage(content="partial-patch", response_metadata=metadata)]}
    result = coding.generate_code("Fix", "code", user_id="u", session_id="s")
    assert json.loads(result)["success"] is False
    assert "partial-patch" not in result


def test_model_options_and_usage_survive_real_manager_invoke(monkeypatch):
    from chat.backend.agent import llm

    model = MagicMock()
    model.model_name = "gpt-6.1-sol"
    model.invoke.return_value = AIMessage(content="patch", usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120})
    factory = MagicMock(return_value=model)
    store = MagicMock(return_value=True)
    monkeypatch.setattr(llm, "create_chat_model", factory)
    monkeypatch.setattr(LLMUsageTracker, "store_usage", store)
    monkeypatch.setattr(LLMUsageTracker, "calculate_cost", lambda *a, **k: 0.0004)
    options = {"reasoning": {"effort": "medium", "summary": "auto"}, "max_tokens": 12000}
    manager = LLMManager(main_model="openai/gpt-6.1-sol", vision_model="openai/gpt-6.1-sol", provider_mode="openai", model_kwargs=options)
    manager.invoke("Draft", user_id="u", session_id="s", request_type="code_generation")
    assert all(call.kwargs["reasoning"]["effort"] == "medium" for call in factory.call_args_list)
    usage = store.call_args.args[0]
    assert (usage.user_id, usage.session_id, usage.request_type) == ("u", "s", "code_generation")
    assert (usage.input_tokens, usage.output_tokens) == (100, 20)


def test_coding_model_is_registered_and_costs_correctly():
    assert ModelMapper.get_native_name("openai/gpt-6.1-sol", "openai") == "gpt-6.1-sol"
    assert LLMUsageTracker.calculate_cost(1000, 1000, "openai/gpt-6.1-sol", use_dynamic_pricing=False) == pytest.approx(0.012)
    assert LLMUsageTracker.calculate_cost(300000, 1000, "openai/gpt-6.1-sol", use_dynamic_pricing=False) == pytest.approx(1.215)


def test_tool_schema_hides_user_and_session():
    assert set(coding.GenerateCodeArgs.model_json_schema()["properties"]) == {"task", "context"}


def test_oversized_proposal_is_not_sent_through_summarization(manager):
    manager.return_value.invoke.return_value = {"messages": [AIMessage(content="patch" * 9000)]}
    result = json.loads(coding.generate_code("Fix", "code", user_id="u", session_id="s"))
    assert result["success"] is False
    assert "proposal" not in result


def test_role_registration_keeps_sol_out_of_default_investigations():
    from chat.backend.agent.utils.chat_context_manager import ChatContextManager
    from chat.backend.agent.utils.model_cutoff_manager import ModelCutoffManager

    assert ModelConfig.CODING_MODEL == "openai/gpt-6.1-sol"
    assert ModelConfig.CODING_MODEL in ChatContextManager.MODEL_CONTEXT_LIMITS
    assert ModelConfig.CODING_MODEL in ModelCutoffManager().models
    assert ModelConfig.MAIN_MODEL == ModelConfig.RCA_MODEL == "openai/gpt-6.1-terra"
