"""
OpenAI provider implementation for direct API access.

Uses the official OpenAI API instead of going through OpenRouter.
Requires OPENAI_API_KEY environment variable.
"""

import logging
import os

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from utils.openai_config import openai_client_kwargs, openai_deployment_name

from .base_provider import BaseLLMProvider
from ..model_mapper import ModelMapper

logger = logging.getLogger(__name__)


class OpenAIProvider(BaseLLMProvider):
    """Direct OpenAI API provider."""

    def __init__(self):
        super().__init__()
        self.client_config = openai_client_kwargs()
        self.api_key = self.client_config["api_key"]

    def get_chat_model(
        self,
        model: str,
        temperature: float = 0.4,
        **kwargs
    ) -> BaseChatModel:
        """
        Return a configured ChatOpenAI instance for direct OpenAI API access.

        Args:
            model: Model name (accepts both OpenRouter format and native format)
            temperature: Temperature setting (default 0.4)
            **kwargs: Additional parameters

        Returns:
            Configured ChatOpenAI instance

        Raises:
            RuntimeError: If OpenAI API key is not configured
            ValueError: If model is not supported by OpenAI
        """
        if not self.is_available():
            raise RuntimeError("OpenAI provider is not available. Please set OPENAI_API_KEY.")

        if not self.supports_model(model):
            raise ValueError(f"Model {model} is not supported by OpenAI provider")

        # Convert to native OpenAI format
        native_model = ModelMapper.get_native_name(model, 'openai')

        logger.info(f"Creating OpenAI chat model: {native_model}")

        config = {
            **self.client_config,
            "model": openai_deployment_name(native_model),
            "temperature": temperature,
            "request_timeout": 120.0,
            "max_retries": 3,
            "stream_usage": True,
        }

        # Reasoning models (GPT-5+, o-series) require the Responses API
        # (/v1/responses) when tools are combined with reasoning effort —
        # Chat Completions returns 400 for that combination. They also
        # reject the `temperature` parameter outright. `summary: "auto"`
        # surfaces reasoning summaries to the streaming output so they
        # flow into the ThoughtsPanel / sub-agent panes during RCA.
        if self._supports_reasoning(native_model):
            effort = os.getenv("OPENAI_REASONING_EFFORT", "low").strip().lower() or "low"
            if effort not in {"none", "minimal", "low", "medium", "high", "xhigh", "max"}:
                logger.error("Invalid OpenAI reasoning effort configuration")
                raise ValueError("Invalid OPENAI_REASONING_EFFORT")
            if native_model.startswith("gpt-6.2-sol") and effort in {"none", "minimal"}:
                effort = "low"
            # Legacy reasoning models reject the newer low/none levels.
            if native_model.startswith("gpt-5-pro"):
                effort = "high"
            elif "-pro" in native_model or "chat-latest" in native_model:
                effort = "medium" if effort in {"none", "minimal", "low"} else effort
            config["reasoning"] = {"effort": effort, "summary": "auto"}
            config["use_responses_api"] = True
            config.pop("temperature", None)
            logger.info(
                "Enabled OpenAI Responses API for model %s with reasoning effort %s", native_model, effort
            )


        config.update(kwargs)

        return ChatOpenAI(**config)

    def is_available(self) -> bool:
        """Check if OpenAI API key is configured."""
        return bool(self.api_key)

    def supports_model(self, model: str) -> bool:
        """
        Check if this is an OpenAI model.

        Args:
            model: Model name to check

        Returns:
            True if this is an OpenAI model
        """
        if "/" in model:
            return model.split("/")[0] == "openai"
        return ModelMapper.is_model_supported_by_provider(model, 'openai')

    def get_native_model_name(self, model: str) -> str:
        """
        Convert model name to OpenAI native format.

        Args:
            model: Model name in any format

        Returns:
            Model name in OpenAI native format
        """
        return ModelMapper.get_native_name(model, 'openai')

    @staticmethod
    def _supports_reasoning(native_model: str) -> bool:
        """Check if an OpenAI model supports the reasoning_effort parameter."""
        name = native_model.lower()
        # Exclude older models that don't support reasoning.
        # Everything else (gpt-5+, o-series, future models) gets it.
        non_reasoning = ("gpt-3", "gpt-4")
        return not name.startswith(non_reasoning)

    def get_supported_models(self) -> list[str]:
        """Get list of OpenAI models in OpenRouter format."""
        return ModelMapper.get_supported_models_for_provider('openai')
