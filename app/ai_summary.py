from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SummaryResult:
    text: str
    source: str
    input_bytes: int
    error: str | None = None


def generate_summary(report: dict[str, Any], fallback: str) -> SummaryResult:
    facts_json, input_bytes = prepare_facts(report)
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return SummaryResult(fallback, "rules_no_api_key", input_bytes)

    model = os.getenv("OPENAI_MODEL", "gpt-5-mini")
    payload = {
        "model": model,
        "store": False,
        "instructions": (
            "Kirjuta kodukliendile 1–3 lühikest eestikeelset lauset. "
            "Kasuta ainult sisendis olevaid fakte. Ära arvuta ise ega lisa uusi soovituspiire. "
            "Maini kõige olulisemat ebatavalist sündmust ja anduri vaikimist või puudulikku "
            "andmestikku, kui see on sisendis. Ära kasuta markdowni."
        ),
        "input": facts_json,
        "max_output_tokens": 180,
        "text": {"verbosity": "low"},
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            body = json.loads(response.read().decode("utf-8"))
        text = _extract_output_text(body)
        if not text:
            raise ValueError("AI response did not contain output text")
        return SummaryResult(text.strip(), "openai", input_bytes)
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return SummaryResult(fallback, "rules_ai_error", input_bytes, type(exc).__name__)


def prepare_facts(report: dict[str, Any]) -> tuple[str, int]:
    facts = {
        "language": "et",
        "room": report["room"],
        "requested_hours": report["requested_hours"],
        "sample_count": report["sample_count"],
        "coverage_minutes": report["coverage_minutes"],
        "period_start": report["period_start"],
        "period_end": report["period_end"],
        "statistics": report["statistics"],
        "anomalies": report["anomalies"],
        "device_status": report["device_status"],
        "thresholds": report["thresholds"],
    }
    facts_json = json.dumps(facts, ensure_ascii=False, separators=(",", ":"))
    input_bytes = len(facts_json.encode("utf-8"))
    return facts_json, input_bytes


def _extract_output_text(response: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in response.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                parts.append(str(content["text"]))
    return "\n".join(parts)
