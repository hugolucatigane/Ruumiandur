from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


SYSTEM_INSTRUCTIONS = (
    "Toimeta välja deterministic_draft 1–3 lühikeseks ja loomuliku kõlaga eestikeelseks "
    "lauseks. Säilita kõik mustandis olevad faktid ja arvud; teisi välju kasuta ainult nende "
    "kontrollimiseks. Ära arvuta, lisa soovitusi ega uusi väiteid. Kui andmekatvus pole piisav, "
    "säilita see hoiatus ja ära nimeta kogu perioodi normaalseks. Kui faktides on kinni jäänud "
    "anduri hoiatus, säilita see ning ära nimeta vastavat mõõtekanalit usaldusväärseks. "
    "Ära maini JSON-i välju, "
    "andmestruktuuri ega tühja sündmuste loendit. Ära pöördu lugeja poole, kasuta ingliskeelset "
    "sõna 'online' ega markdowni. Väljasta ainult lõpptekst."
)

AI_EXCEPTIONS = (
    urllib.error.URLError,
    TimeoutError,
    ValueError,
    KeyError,
    json.JSONDecodeError,
)


@dataclass(frozen=True)
class SummaryResult:
    text: str
    source: str
    input_bytes: int
    error: str | None = None


def generate_summary(report: dict[str, Any], fallback: str) -> SummaryResult:
    facts_json, input_bytes = prepare_facts(report, deterministic_draft=fallback)
    provider = os.getenv("AI_PROVIDER", "auto").strip().lower()
    if provider == "rules":
        return SummaryResult(fallback, "rules_requested", input_bytes)
    if provider not in {"auto", "ollama", "openai"}:
        return SummaryResult(
            fallback,
            "rules_ai_error",
            input_bytes,
            f"config:unknown_provider:{provider}",
        )

    errors: list[str] = []
    if provider in {"auto", "ollama"}:
        try:
            return SummaryResult(_generate_with_ollama(facts_json), "ollama", input_bytes)
        except AI_EXCEPTIONS as exc:
            errors.append(f"ollama:{type(exc).__name__}")
            if provider == "ollama":
                return SummaryResult(fallback, "rules_ai_error", input_bytes, errors[0])

    if provider in {"auto", "openai"}:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if api_key:
            try:
                return SummaryResult(
                    _generate_with_openai(facts_json, api_key),
                    "openai",
                    input_bytes,
                )
            except AI_EXCEPTIONS as exc:
                errors.append(f"openai:{type(exc).__name__}")
        elif provider == "openai":
            return SummaryResult(fallback, "rules_no_api_key", input_bytes)
        else:
            errors.append("openai:no_api_key")

    return SummaryResult(
        fallback,
        "rules_no_ai_available" if provider == "auto" else "rules_ai_error",
        input_bytes,
        ";".join(errors),
    )


def _generate_with_ollama(facts_json: str) -> str:
    base_url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    payload = {
        "model": os.getenv("OLLAMA_MODEL", "qwen3:8b"),
        "system": SYSTEM_INSTRUCTIONS,
        "prompt": facts_json,
        "stream": False,
        "think": False,
        "keep_alive": "5m",
        "options": {"temperature": 0.2, "num_predict": 180},
    }
    request = urllib.request.Request(
        f"{base_url}/api/generate",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        body = json.loads(response.read().decode("utf-8"))
    raw_text = body.get("response")
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise ValueError("Ollama response did not contain text")
    return raw_text.strip()


def _generate_with_openai(facts_json: str, api_key: str) -> str:
    payload = {
        "model": os.getenv("OPENAI_MODEL", "gpt-5.6-luna"),
        "store": False,
        "instructions": SYSTEM_INSTRUCTIONS,
        "input": facts_json,
        "max_output_tokens": 300,
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
    with urllib.request.urlopen(request, timeout=20) as response:
        body = json.loads(response.read().decode("utf-8"))
    text = _extract_output_text(body).strip()
    if not text:
        raise ValueError("OpenAI response did not contain output text")
    return text


def prepare_facts(
    report: dict[str, Any],
    deterministic_draft: str | None = None,
) -> tuple[str, int]:
    facts = {
        "language": "et",
        "requested_hours": report["requested_hours"],
        "sample_count": report["sample_count"],
        "expected_sample_count": report["expected_sample_count"],
        "coverage_minutes": report["coverage_minutes"],
        "coverage_percent": report["coverage_percent"],
        "coverage_sufficient": report["coverage_sufficient"],
        "minimum_coverage_percent": report["minimum_coverage_percent"],
        "period_start": report["period_start"],
        "period_end": report["period_end"],
        "statistics": report["statistics"],
        "anomalies": report["anomalies"],
        "device_status": report["device_status"],
        "thresholds": report["thresholds"],
    }
    if deterministic_draft is not None:
        facts["deterministic_draft"] = deterministic_draft
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
