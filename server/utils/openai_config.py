"""Shared OpenAI/Azure v1 endpoint and deployment-name configuration."""

import json
import logging
import os
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)


def openai_client_kwargs() -> dict:
    """Use the same API key and endpoint for chat and embeddings."""
    config = {"api_key": os.getenv("OPENAI_API_KEY", "").strip()}
    endpoint = (os.getenv("OPENAI_BASE_URL") or os.getenv("OPENAI_API_BASE") or "").strip()
    if endpoint:
        parsed = urlsplit(endpoint)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            logger.error("Invalid OpenAI base URL configuration")
            raise ValueError("OPENAI_BASE_URL must be an HTTP(S) URL without credentials, query, or fragment")
        config["base_url"] = endpoint.rstrip("/") + "/"
    return config


def openai_deployments() -> dict[str, str]:
    """Map canonical native model IDs to Azure deployment names, when configured."""
    raw = os.getenv("OPENAI_DEPLOYMENTS", "").strip()
    if not raw:
        return {}
    try:
        deployments = json.loads(raw)
    except (ValueError, TypeError):
        logger.error("Invalid OpenAI deployment mapping JSON")
        raise ValueError("OPENAI_DEPLOYMENTS must be a JSON object of model IDs to deployment names") from None
    if not isinstance(deployments, dict) or any(
        not isinstance(model, str) or not model.strip() or "/" in model
        or not isinstance(deployment, str) or not deployment.strip() or "/" in deployment
        or model != model.strip() or deployment != deployment.strip()
        for model, deployment in deployments.items()
    ):
        logger.error("Invalid OpenAI deployment mapping entries")
        raise ValueError("OPENAI_DEPLOYMENTS requires non-empty native model IDs and deployment names without slashes or surrounding whitespace")
    if len(set(deployments.values())) != len(deployments):
        logger.error("Ambiguous OpenAI deployment mapping")
        raise ValueError("OPENAI_DEPLOYMENTS must use a distinct deployment name for each model")
    return deployments


def openai_deployment_name(native_model: str) -> str:
    """Resolve a canonical model at the API boundary, including embedding models."""
    return openai_deployments().get(native_model, native_model)


def canonical_openai_model(model: str) -> str:
    """Recover canonical IDs for context and cost tracking of deployment aliases."""
    if "/" in model and not model.startswith("openai/"):
        return model
    native = model.removeprefix("openai/")
    for canonical, deployment in openai_deployments().items():
        if native == deployment:
            return "openai/" + canonical
    return model
