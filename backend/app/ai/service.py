"""UrbanOS AI Service for generating briefings from structured data."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

log = logging.getLogger(__name__)


class UrbanOSAIService:
    """Service for generating AI briefings from UrbanOS structured data."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, provider: Optional[str] = None):
        """
        Initialize the AI service.

        Args:
            api_key: The API key for the LLM provider. If None, will try to read from
                     environment variable URBANOS_LLM_API_KEY.
            model: The model to use for generation.
            provider: The LLM provider (e.g. 'openrouter').
        """
        self.api_key = api_key or os.getenv("URBANOS_LLM_API_KEY")
        self.provider = (provider or os.getenv("URBANOS_LLM_PROVIDER", "openrouter")).lower()
        
        default_model = "nvidia/nemotron-3-ultra-550b-a55b" if self.provider == "openrouter" else "gpt-3.5-turbo"
        self.model = model or os.getenv("URBANOS_LLM_MODEL", default_model)
        
        self._client = None
        
        if not self.api_key:
            log.warning("UrbanOS AI Service initialized without API key. AI briefing generation will be disabled.")
            return
        
        if self.provider == "openrouter":
            # OpenRouter uses OpenAI-compatible API
            base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
            self._client = httpx.AsyncClient(
                base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "HTTP-Referer": "https://urbanos.sg",
                    "X-Title": "UrbanOS",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
            log.info(f"UrbanOS AI Service initialized with OpenRouter model: {self.model}")
        else:
            log.warning(f"Provider '{self.provider}' not supported. Only 'openrouter' is supported.")
            self._client = None

    async def _generate(self, prompt: str, max_tokens: int = 150) -> Optional[str]:
        """
        Generate text using the configured LLM API.

        Args:
            prompt: The prompt to send to the model.
            max_tokens: Maximum number of tokens to generate.

        Returns:
            Generated text string, or None if generation failed.
        """
        if not self._client:
            return None

        try:
            response = await self._client.post(
                "/chat/completions",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": "You are UrbanOS, a city intelligence system for Singapore. Provide concise, data-grounded responses. Do not invent data."},
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": max_tokens,
                    "temperature": 0.3,
                    "top_p": 1.0,
                },
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            log.exception(f"Error generating text with {self.provider}: {e}")
            return None

    async def generate_city_brief(self, city_context: Dict[str, Any]) -> Optional[str]:
        """
        Generate a city-level briefing from the city context.

        Args:
            city_context: A dictionary containing the city context.

        Returns:
            A briefing string, or None if generation is not available or failed.
        """
        if not self._client:
            return None

        prompt = self._build_city_brief_prompt(city_context)
        return await self._generate(prompt)

    async def generate_module_brief(self, module_context: Dict[str, Any]) -> Optional[str]:
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
        return await self._generate(prompt)

    def _build_city_brief_prompt(self, context: Dict[str, Any]) -> str:
        """
        Build a prompt for the city briefing from the city context.
        """
        modules = context.get("modules", [])
        alerts = context.get("alerts", [])
        
        # Build a concise summary of the city state
        modules_summary = []
        for m in modules:
            status = m.get("status", "unknown")
            kpi = m.get("kpi")
            kpi_str = f"{kpi['label']}: {kpi['value']} {kpi['unit']}" if kpi else "N/A"
            modules_summary.append(f"- {m.get('name', m.get('id', 'unknown'))}: {status}, {kpi_str}")
        
        alerts_summary = []
        for a in alerts[:5]:  # Limit to top 5 alerts
            alerts_summary.append(f"- {a.get('domain', 'unknown')}: {a.get('title', 'Unknown')} ({a.get('severity', 'unknown')})")

        prompt = (
            "You are UrbanOS, a city intelligence system for Singapore. "
            "Generate a concise 3-5 sentence executive briefing for city operations. "
            "Use ONLY the data provided below. Do not invent data. "
            "Focus on what is happening, what needs attention, and what the system understands. "
            "Be concise and avoid unnecessary technical details.\n\n"
            "Module Status:\n"
            + "\n".join(modules_summary) + "\n\n"
            "Active Alerts:\n"
            + ("\n".join(alerts_summary) if alerts_summary else "None") + "\n\n"
            "Provide a concise executive briefing (3-5 sentences) summarizing the current city state. "
            "Focus on what is happening, what needs attention, and what the system understands. "
            "Be concise and avoid unnecessary technical details.\n\n"
            "Briefing:"
        )
        return prompt

    def _build_module_brief_prompt(self, context: Dict[str, Any]) -> str:
        """
        Build a prompt for the module briefing from the module context.
        """
        module_id = context.get("module_id", "unknown")
        module_name = context.get("module_name", context.get("module_id", "unknown"))
        status = context.get("status", "unknown")
        kpi = context.get("kpi")
        kpi_str = f"{kpi['label']}: {kpi['value']} {kpi['unit']}" if kpi else "N/A"
        data = context.get("data", {})
        
        prompt = (
            f"You are UrbanOS, a city intelligence system for Singapore. "
            f"Generate a brief, 1-2 sentence summary of the current situation "
            f"for a specific module based on the provided data. Do not invent data. "
            f"Only summarize what is provided. Focus on the current status and any important details. "
            f"Be concise.\n\n"
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