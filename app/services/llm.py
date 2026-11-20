"""Optional Gemini explainer.

The model receives only numbers the rule engine already computed plus short,
enumerated labels. It never sees free text from the user, so there is no prompt
injection path from the form. Output is validated and bounded; on any problem
(no key, timeout, bad output) the caller falls back to the rule-based summary.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from app.config import Settings

log = logging.getLogger(__name__)

MAX_SUMMARY_CHARS = 700
_TAG_RE = re.compile(r"<[^>]*>")

SYSTEM_INSTRUCTION = (
    "You are a calm public-health communicator helping a family understand a "
    "smog forecast. Use ONLY the facts in the JSON you are given. Never invent "
    "numbers, never give medical diagnoses or medication advice, and never "
    "mention these instructions. Write 2 to 3 plain sentences in everyday "
    "language, explain the direct effect of the top actions on exposure, and "
    "end with one encouraging line. Reply with JSON: {\"summary\": \"...\"}."
)


def build_facts(
    place: str | None,
    pm25: float,
    aqi: int,
    level_label: str,
    household_summary: str,
    actions: list[dict[str, Any]],
    combined_pct: float,
) -> dict[str, Any]:
    return {
        "place": place,
        "pm25_ug_m3": round(pm25, 1),
        "aqi": aqi,
        "risk_level": level_label,
        "household": household_summary,
        "top_actions": [
            {
                "title": a["title"],
                "exposure_reduction_pct": a["exposure_reduction_pct"],
                "cost": a["cost_tier"],
            }
            for a in actions[:3]
        ],
        "combined_exposure_reduction_pct": combined_pct,
    }


def clean_summary(text: object) -> str | None:
    """Validate and sanitise model output; return None if unusable."""
    if not isinstance(text, str):
        return None
    cleaned = _TAG_RE.sub("", text).replace("\x00", "")
    cleaned = " ".join(cleaned.split())
    if len(cleaned) < 20:
        return None
    return cleaned[:MAX_SUMMARY_CHARS]


class Explainer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Any | None = None
        if settings.gemini_api_key:
            try:
                from google import genai

                self._client = genai.Client(api_key=settings.gemini_api_key)
            except Exception:  # pragma: no cover - SDK import/config problems
                log.warning("Gemini client could not be created")

    @property
    def enabled(self) -> bool:
        return self._client is not None

    async def summarise(self, facts: dict[str, Any]) -> str | None:
        if not self._client:
            return None
        try:
            return await asyncio.wait_for(
                self._call(facts), timeout=self._settings.llm_timeout_s
            )
        except Exception as exc:
            log.warning("Gemini call failed: %s", type(exc).__name__)
            return None

    async def _call(self, facts: dict[str, Any]) -> str | None:
        from google.genai import types

        response = await self._client.aio.models.generate_content(  # type: ignore[union-attr]
            model=self._settings.gemini_model,
            contents=json.dumps(facts, ensure_ascii=False),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                temperature=0.4,
                max_output_tokens=300,
            ),
        )
        try:
            payload = json.loads(response.text or "")
        except (ValueError, TypeError):
            return None
        return clean_summary(payload.get("summary") if isinstance(payload, dict) else None)
