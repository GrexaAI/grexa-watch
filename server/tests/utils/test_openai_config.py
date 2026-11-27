"""Shared Azure/OpenAI configuration stays consistent across API clients."""

import pytest

from utils.openai_config import (
    canonical_openai_model,
    openai_client_kwargs,
    openai_deployment_name,
    openai_deployments,
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_API_BASE", "OPENAI_DEPLOYMENTS"):
        monkeypatch.delenv(key, raising=False)


def test_public_openai_uses_sdk_default_endpoint(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    assert openai_client_kwargs() == {"api_key": "test-key"}
    assert openai_deployment_name("gpt-6.1-terra") == "gpt-6.1-terra"


def test_azure_v1_endpoint_is_shared(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.openai.azure.com/openai/v1")
    assert openai_client_kwargs()["base_url"] == "https://example.openai.azure.com/openai/v1/"


def test_legacy_base_url_alias_is_supported(monkeypatch):
    monkeypatch.setenv("OPENAI_API_BASE", "https://legacy.example/v1/")
    assert openai_client_kwargs()["base_url"] == "https://legacy.example/v1/"
    monkeypatch.setenv("OPENAI_BASE_URL", "https://preferred.example/v1/")
    assert openai_client_kwargs()["base_url"] == "https://preferred.example/v1/"


@pytest.mark.parametrize("url", ["not-a-url", "ftp://example.com", "https://user:secret@example.com", "https://example.com?api-key=secret"])
def test_invalid_endpoint_does_not_leak_secrets(monkeypatch, caplog, url):
    monkeypatch.setenv("OPENAI_BASE_URL", url)
    with pytest.raises(ValueError, match="OPENAI_BASE_URL"):
        openai_client_kwargs()
    assert "secret" not in caplog.text


def test_aliases_round_trip_and_cover_embeddings(monkeypatch):
    monkeypatch.setenv("OPENAI_DEPLOYMENTS", '{"gpt-6.1-terra":"prod-terra","text-embedding-3-small":"embed-prod"}')
    assert openai_deployment_name("gpt-6.1-terra") == "prod-terra"
    assert canonical_openai_model("prod-terra") == "openai/gpt-6.1-terra"
    assert canonical_openai_model("openai/prod-terra") == "openai/gpt-6.1-terra"
    assert openai_deployment_name("text-embedding-3-small") == "embed-prod"
    assert canonical_openai_model("google/prod-terra") == "google/prod-terra"
    assert canonical_openai_model("gpt-6-luna") == "gpt-6-luna"


@pytest.mark.parametrize("value", ["bad-json-secret", "[]", '{"gpt-6-luna":null}', '{"openai/gpt-6-luna":"alias"}', '{"gpt-6-luna":""}', '{"gpt-6-luna":"same","gpt-6.1-terra":"same"}'])
def test_invalid_aliases_fail_without_logging_contents(monkeypatch, caplog, value):
    monkeypatch.setenv("OPENAI_DEPLOYMENTS", value)
    with pytest.raises(ValueError, match="OPENAI_DEPLOYMENTS"):
        openai_deployments()
    assert "bad-json-secret" not in caplog.text
