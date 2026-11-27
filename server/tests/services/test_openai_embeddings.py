"""Embedding calls follow the same Azure endpoint and aliases as chat."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytest.importorskip("openai")

from services.correlation.embedding_client import EmbeddingClient


def test_azure_embedding_uses_shared_endpoint_and_deployment(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "openai/text-embedding-3-small")
    monkeypatch.setenv("OPENAI_API_KEY", "azure-test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.openai.azure.com/openai/v1/")
    monkeypatch.setenv("OPENAI_DEPLOYMENTS", '{"text-embedding-3-small":"embedding-prod"}')
    sdk = Mock()
    sdk.embeddings.create.return_value = SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2])])
    constructor = Mock(return_value=sdk)
    monkeypatch.setattr("openai.OpenAI", constructor)
    assert EmbeddingClient().embed("incident") == [0.1, 0.2]
    constructor.assert_called_once_with(api_key="azure-test-key", base_url="https://example.openai.azure.com/openai/v1/")
    sdk.embeddings.create.assert_called_once_with(input="incident", model="embedding-prod")


def test_missing_embedding_key_uses_similarity_fallback(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "openai/text-embedding-3-small")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)
    assert EmbeddingClient().embed("incident") is None
