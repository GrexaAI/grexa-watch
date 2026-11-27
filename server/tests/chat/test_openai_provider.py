"""OpenAI direct provider compatibility tests."""

import importlib.util
import os
import sys
import types
import json

import pytest

try:
    import httpx
    from langchain_openai import ChatOpenAI as RealChatOpenAI
except ImportError:
    RealChatOpenAI = None

_SDK_MODULES = {name: sys.modules.get(name) for name in (
    "langchain_openai", "langchain_core", "langchain_core.language_models",
    "langchain_core.language_models.chat_models",
)}


_SERVER_DIR = os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
_PROVIDER_PATH = os.path.join(
    _SERVER_DIR, "chat", "backend", "agent", "providers", "openai_provider.py"
)


@pytest.fixture()
def openai_provider_module(monkeypatch):
    """Load the provider with minimal dependency stubs."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    for key in ("OPENAI_BASE_URL", "OPENAI_API_BASE", "OPENAI_DEPLOYMENTS", "OPENAI_REASONING_EFFORT"):
        monkeypatch.delenv(key, raising=False)

    langchain_openai = types.ModuleType("langchain_openai")
    langchain_core = types.ModuleType("langchain_core")
    language_models = types.ModuleType("langchain_core.language_models")
    chat_models = types.ModuleType("langchain_core.language_models.chat_models")

    class ChatOpenAI:
        def __init__(self, **config):
            self.config = config

    class BaseChatModel:
        pass

    langchain_openai.ChatOpenAI = ChatOpenAI
    chat_models.BaseChatModel = BaseChatModel

    base_provider = types.ModuleType("chat.backend.agent.providers.base_provider")

    class BaseLLMProvider:
        def __init__(self):
            pass  # Stub — real implementation lives in base_provider.py

    base_provider.BaseLLMProvider = BaseLLMProvider

    model_mapper = types.ModuleType("chat.backend.agent.model_mapper")

    class ModelMapper:
        @staticmethod
        def get_native_name(model_name, target_provider):
            assert target_provider == "openai"
            return model_name.split("/", 1)[1] if "/" in model_name else model_name

        @staticmethod
        def is_model_supported_by_provider(model_name, provider):
            return provider == "openai" and model_name.startswith("gpt-")

        @staticmethod
        def get_supported_models_for_provider(provider):
            return ["openai/gpt-5.5"] if provider == "openai" else []

    model_mapper.ModelMapper = ModelMapper

    monkeypatch.setitem(sys.modules, "langchain_openai", langchain_openai)
    monkeypatch.setitem(sys.modules, "langchain_core", langchain_core)
    monkeypatch.setitem(sys.modules, "langchain_core.language_models", language_models)
    monkeypatch.setitem(
        sys.modules, "langchain_core.language_models.chat_models", chat_models
    )
    monkeypatch.setitem(
        sys.modules, "chat.backend.agent.providers.base_provider", base_provider
    )
    monkeypatch.setitem(sys.modules, "chat.backend.agent.model_mapper", model_mapper)

    spec = importlib.util.spec_from_file_location(
        "chat.backend.agent.providers.openai_provider", _PROVIDER_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_reasoning_model_uses_responses_api(openai_provider_module):
    provider = openai_provider_module.OpenAIProvider()

    model = provider.get_chat_model("openai/gpt-5.5", streaming=True)

    assert model.config["model"] == "gpt-5.5"
    assert model.config["streaming"] is True
    assert "reasoning_effort" not in model.config
    assert model.config["reasoning"] == {"effort": "low", "summary": "auto"}
    assert model.config["use_responses_api"] is True
    assert "temperature" not in model.config


def test_azure_deployment_uses_v1_endpoint_and_key(openai_provider_module, monkeypatch):
    """Azure aliases affect API requests without changing the canonical model ID."""
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.openai.azure.com/openai/v1/")
    monkeypatch.setenv("OPENAI_API_KEY", "azure-test-key")
    monkeypatch.setenv("OPENAI_DEPLOYMENTS", '{"gpt-6.1-terra":"prod-terra"}')
    model = openai_provider_module.OpenAIProvider().get_chat_model("openai/gpt-6.1-terra")
    assert model.config["model"] == "prod-terra"
    assert model.config["base_url"] == "https://example.openai.azure.com/openai/v1/"
    assert model.config["api_key"] == "azure-test-key"
    assert model.config["use_responses_api"] is True
    assert "temperature" not in model.config


@pytest.mark.parametrize("effort", ["none", "low", "medium", "high"])
def test_terra_reasoning_is_configurable(openai_provider_module, monkeypatch, effort):
    """Terra honors the operator's reasoning budget."""
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", effort)
    model = openai_provider_module.OpenAIProvider().get_chat_model("openai/gpt-6.1-terra")
    assert model.config["reasoning"]["effort"] == effort


def test_invalid_reasoning_configuration_fails_early(openai_provider_module, monkeypatch):
    """A typo must fail before an API request rather than spend retries."""
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "cheap")
    with pytest.raises(ValueError, match="OPENAI_REASONING_EFFORT"):
        openai_provider_module.OpenAIProvider().get_chat_model("openai/gpt-6.1-terra")


def test_guardrail_can_override_reasoning(openai_provider_module):
    """A utility call can turn reasoning off without changing investigation defaults."""
    model = openai_provider_module.OpenAIProvider().get_chat_model(
        "openai/gpt-6-luna", reasoning={"effort": "none"}
    )
    assert model.config["reasoning"] == {"effort": "none"}


def test_legacy_model_keeps_temperature(openai_provider_module):
    """Non-reasoning OpenAI models retain their existing API behavior."""
    model = openai_provider_module.OpenAIProvider().get_chat_model("openai/gpt-4.1", temperature=0.2)
    assert model.config["temperature"] == 0.2
    assert "reasoning" not in model.config


def test_missing_key_fails_before_creating_model(openai_provider_module, monkeypatch):
    """Both OpenAI and Azure require the operator's resource-specific API key."""
    monkeypatch.delenv("OPENAI_API_KEY")
    provider = openai_provider_module.OpenAIProvider()
    assert not provider.is_available()
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        provider.get_chat_model("openai/gpt-6.1-terra")


@pytest.mark.skipif(not isinstance(RealChatOpenAI, type), reason="optional real SDK compatibility test")
@pytest.mark.parametrize("model_id,coding", [("gpt-6.1-terra", False), ("gpt-6.1-sol", True)])
def test_real_sdk_sends_azure_responses_request(openai_provider_module, monkeypatch, model_id, coding):
    """Exercise actual LangChain/OpenAI serialization without network or paid calls."""
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.openai.azure.com/openai/v1/")
    monkeypatch.setenv("OPENAI_DEPLOYMENTS", json.dumps({model_id: "prod-model"}))
    monkeypatch.setattr(openai_provider_module, "ChatOpenAI", RealChatOpenAI)
    for name, module in _SDK_MODULES.items():
        if module is not None:
            monkeypatch.setitem(sys.modules, name, module)
    captured = []

    def respond(request):
        captured.append(request)
        return httpx.Response(200, json={
            "id": "resp_test", "object": "response", "created_at": 1,
            "status": "completed", "model": model_id,
            "output": [{"id": "msg_test", "type": "message", "role": "assistant",
                        "status": "completed", "content": [{"type": "output_text", "text": "Ready", "annotations": []}]}],
            "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
        })

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        llm = openai_provider_module.OpenAIProvider().get_chat_model(
            "openai/" + model_id, http_client=client,
            **({"reasoning": {"effort": "medium", "summary": "auto"}, "max_tokens": 12000} if coding else {}),
        )
        llm.bind_tools([{
            "name": "query_counts", "description": "Read aggregate counts",
            "parameters": {"type": "object", "properties": {}},
        }]).invoke("Hello")
    assert len(captured) == 1
    assert str(captured[0].url) == "https://example.openai.azure.com/openai/v1/responses"
    assert captured[0].headers["Authorization"] == "Bearer test-key"
    payload = json.loads(captured[0].content)
    assert payload["model"] == "prod-model"
    assert payload["reasoning"]["effort"] == ("medium" if coding else "low")
    if coding:
        assert payload["max_output_tokens"] == 12000
    assert payload["tools"][0]["name"] == "query_counts"
    assert payload["tools"][0]["type"] == "function"
    assert "temperature" not in payload
