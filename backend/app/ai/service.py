"""UrbanOS AI Service for generating briefings from structured data."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

try:
    import openai
except ImportError:
    openai = None
    log.warning("OpenAI package not installed. OpenAI support disabled.")

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None
    log.warning("google.genai package not installed. Google AI Studio support disabled.")


class UrbanOSAIService:
    """Service for generating AI briefings from UrbanOS structured data."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, provider: Optional[str] = None):
        """
        Initialize the AI service.

        Args:
            api_key: The API key for the LLM provider. If None, will try to read from
                     environment variable URBANOS_LLM_API_KEY.
            model: The model to use for generation.
            provider: The LLM provider (e.g. 'openai', 'google').
        """
        self.api_key = api_key or os.getenv("URBANOS_LLM_API_KEY")
        self.provider = (provider or os.getenv("URBANOS_LLM_PROVIDER", "openai")).lower()
        
        default_model = "gemma-4-31b" if self.provider == "google" else "gpt-3.5-turbo"
        self.model = model or os.getenv("URBANOS_LLM_MODEL", default_model)
        
        self._client = None

        if not self.api_key:
            log.warning("UrbanOS AI Service initialized without API key. AI briefing generation will be disabled.")
            return

        if self.provider == "google":
            if genai:
                self._client = genai.Client(api_key=self.api_key)
                log.info(f"UrbanOS AI Service initialized with Google model: {self.model}")
            else:
                log.warning("Provider set to 'google' but google.genai is not installed.")
        else:
            if openai:
                openai.api_key = self.api_key
                self._client = openai
                log.info(f"UrbanOS AI Service initialized with OpenAI model: {self.model}")
            else:
                log.warning("Provider set to 'openai' but openai package is not installed.")

    def _generate_with_openai(self, prompt: str, max_tokens: int = 150) -> Optional[str]:
        """
        Generate text using the configured LLM API (OpenAI or Google).

        Args:
            prompt: The prompt to send to the model.
            max_tokens: Maximum number of tokens to generate.

        Returns:
            Generated text string, or None if generation failed.
        """
        if not self._client:
            return None

        try:
            if self.provider == "google":
                response = self._client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        max_output_tokens=max_tokens,
                        temperature=0.3,
                    )
                )
                return response.text.strip()
            else:
                response = self._client.Completion.create(
                    engine=self.model,
                    prompt=prompt,
                    max_tokens=max_tokens,
                    temperature=0.3,  # Low temperature for more focused, deterministic output
                    top_p=1.0,
                    frequency_penalty=0.0,
                    presence_penalty=0.0,
                )
                return response.choices[0].text.strip()
        except Exception as e:
            log.exception(f"Error generating text with {self.provider}: {e}")
            return None

    def generate_city_brief(self, city_context: Dict[str, Any]) -> Optional[str]:
        """
        Generate a city-level briefing from the city context.

        Args:
            city_context: A dictionary containing the city context (from CitySituationReport).

        Returns:
            A briefing string, or None if generation is not available or failed.
        """
        if not self._client:
            return None

        # Construct a prompt that instructs the LLM to summarize the city context.
        prompt = self._build_city_brief_prompt(city_context)
        return self._generate_with_openai(prompt)

    def generate_module_brief(self, module_context: Dict[str, Any]) -> Optional[str]:
        """
        Generate a module-level briefing from the module context.

        Args:
            module_context: A dictionary containing the module context.

        Returns:
            A briefing string, or None if generation is not available or failed.
        """
        if not self._client:
            return None

        prompt = self._build_module_brief_prompt(module_context)
        return self._generate_with_openai(prompt)

    def _build_city_brief_prompt(self, context: Dict[str, Any]) -> str:
        """
        Build a prompt for the city briefing from the city context.

        We expect the context to be derived from the CitySituationReport.

        We will extract the most relevant information: module statuses, alerts, etc.
        """
        # We'll keep the prompt concise and instruct the LLM to be concise.
        prompt = (
            "You are an AI assistant for UrbanOS, a city intelligence system for Singapore. "
            "Your task is to generate a brief, 2-4 sentence summary of the current city situation "
            "based on the provided data. Do not invent data. Only summarize what is provided. "
            "Focus on what is happening, what needs attention, and what the system understands. "
            "Be concise and avoid unnecessary technical details.\n\n"
            "City Context:\n"
        )

        # We'll format the context as a readable string.
        # We expect context to have keys like 'domain_status', 'priority_incidents', etc.
        # We'll try to extract a summary.

        # For now, we'll just convert the context to a string and hope it's not too large.
        # In a real implementation, we would extract the most relevant fields.
        prompt += json.dumps(context, indent=2, default=str)[:2000]  # Limit to avoid too long prompts
        prompt += "\n\nBriefing:"

        return prompt

    def _build_module_brief_prompt(self, context: Dict[str, Any]) -> str:
        """
        Build a prompt for the module briefing from the module context.
        """
        prompt = (
            "You are an AI assistant for UrbanOS, a city intelligence system for Singapore. "
            "Your task is to generate a brief, 1-2 sentence summary of the current situation "
            "for a specific module based on the provided data. Do not invent data. "
            "Only summarize what is provided. Focus on the current status and any important details. "
            "Be concise.\n\n"
            "Module Context:\n"
        )
        prompt += json.dumps(context, indent=2, default=str)[:2000]
        prompt += "\n\nBriefing:"

        return prompt

    def is_available(self) -> bool:
        """Check if the AI service is available (has API key and client)."""
        return self._client is not None


# We'll create a singleton instance for use in the application.
_ai_service: Optional[UrbanOSAIService] = None


def get_ai_service() -> UrbanOSAIService:
    """Get the singleton AI service instance."""
    global _ai_service
    if _ai_service is None:
        _ai_service = UrbanOSAIService()
    return _ai_service