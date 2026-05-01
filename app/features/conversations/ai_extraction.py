import json
from pathlib import Path

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.core.config import Settings
from app.features.conversations.schemas import ConversationEvent, ConversationEventType, ExtractedConversationFields

AGENT_SYSTEM_PROMPT_PATH = Path(__file__).parents[2] / "agent" / "prompts" / "appointment_agent.md"


class PostCallExtraction(BaseModel):
    extracted_fields: ExtractedConversationFields = Field(default_factory=ExtractedConversationFields)
    summary: str | None = None
    outcome: str | None = None
    next_action: str | None = None


class PostCallExtractionService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def extract(self, events: list[ConversationEvent]) -> PostCallExtraction | None:
        if not self.settings.post_call_ai_extraction_enabled:
            return None
        prompt = self._build_prompt(events)
        if not prompt:
            return None

        for provider in (self._extract_with_anthropic, self._extract_with_openrouter):
            try:
                result = await provider(prompt)
                if result is not None:
                    return result
            except (httpx.HTTPError, KeyError, TypeError, ValueError, ValidationError):
                continue
        return None

    async def _extract_with_anthropic(self, prompt: str) -> PostCallExtraction | None:
        if not self.settings.anthropic_api_key:
            return None
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.settings.claude_model,
                    "max_tokens": 800,
                    "temperature": 0,
                    "system": self._system_prompt(),
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            response.raise_for_status()
        text = response.json()["content"][0]["text"]
        return self._parse_response(text)

    async def _extract_with_openrouter(self, prompt: str) -> PostCallExtraction | None:
        if not self.settings.openrouter_api_key:
            return None
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{self.settings.openrouter_base_url.rstrip('/')}/chat/completions",
                headers={
                    "authorization": f"Bearer {self.settings.openrouter_api_key}",
                    "content-type": "application/json",
                    "http-referer": "http://localhost:8000",
                    "x-title": self.settings.app_name,
                },
                json={
                    "model": self.settings.openrouter_model,
                    "temperature": 0,
                    "messages": [
                        {"role": "system", "content": self._system_prompt()},
                        {"role": "user", "content": prompt},
                    ],
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"]
        return self._parse_response(text)

    @staticmethod
    def _parse_response(text: str) -> PostCallExtraction:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        return PostCallExtraction.model_validate(json.loads(cleaned.strip()))

    def _build_prompt(self, events: list[ConversationEvent]) -> str:
        transcript_lines: list[str] = []
        tool_lines: list[str] = []
        for event in events:
            payload = event.payload
            if event.event_type == ConversationEventType.TRANSCRIPT:
                role = str(payload.get("role", "unknown"))
                text = str(payload.get("text", "")).strip()
                if text:
                    transcript_lines.append(f"{role}: {text}")
            if event.event_type in {
                ConversationEventType.TOOL_COMPLETED,
                ConversationEventType.APPOINTMENT_BOOKED,
                ConversationEventType.TOOL_FAILED,
            }:
                tool_lines.append(json.dumps(payload, default=str))

        if not transcript_lines and not tool_lines:
            return ""

        return "\n".join(
            [
                "Agent system prompt:",
                self._agent_system_prompt(),
                "",
                "Full transcript:",
                "\n".join(transcript_lines) or "No transcript captured.",
                "",
                "Tool events:",
                "\n".join(tool_lines) or "No tool events captured.",
                "",
                "Return only JSON with this exact shape:",
                json.dumps(PostCallExtraction().model_dump(), indent=2),
            ]
        )

    @staticmethod
    def _agent_system_prompt() -> str:
        try:
            return AGENT_SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        except OSError:
            return ""

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You extract post-call appointment analytics from a healthcare receptionist voice call. "
            "Use the transcript and tool events only. Do not invent missing values. "
            "For extracted_fields, return name, phone_number, date, time, and intent as strings or null. "
            "Use ISO date format when possible and HH:MM:SS time format when possible. Return JSON only."
        )
