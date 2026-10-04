"""LLM symptom extraction. The LLM ONLY fills a fixed JSON schema — it never writes advice."""
import json
import logging
import re
from functools import lru_cache
from typing import Literal

import httpx
from pydantic import ConfigDict, ValidationError, create_model

from app.config import get_settings
from app.languages import fewshot, symptoms
from app.pipeline import calllog, lexicon
from app.pipeline.resilience import Flags, ProviderUnavailable, mode_chain, with_retry

log = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You convert a coffee farmer's description into symptom flags. The description may be in Swahili, "
    "Arabic, Hindi or another language. For each symptom key, output 1 if the farmer clearly says it is "
    "present, -1 if they clearly say it is absent, 0 if not mentioned or unclear. Never guess. "
    "Output only JSON matching the schema.\nSymptoms:\n{symptoms}"
)


class ExtractionError(Exception):
    pass


def json_schema() -> dict:
    keys = list(symptoms())
    return {
        "type": "object",
        "properties": {k: {"type": "integer", "enum": [-1, 0, 1]} for k in keys},
        "required": keys,
        "additionalProperties": False,
    }


@lru_cache
def _model():
    fields = {k: (Literal[-1, 0, 1], ...) for k in symptoms()}
    return create_model("SymptomFlags", __config__=ConfigDict(extra="ignore"), **fields)


def _full_flags(partial: dict) -> dict[str, int]:
    return {k: int(partial.get(k, 0)) for k in symptoms()}


def build_messages(text: str) -> list[dict]:
    sym = "\n".join(f"- {k}: {d}" for k, d in symptoms().items())
    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(symptoms=sym)}]
    for examples in fewshot().values():
        for ex in examples:
            messages.append({"role": "user", "content": ex["text"]})
            messages.append({"role": "assistant", "content": json.dumps(_full_flags(ex["flags"]))})
    messages.append({"role": "user", "content": text})
    return messages


def _chat_together(messages: list[dict], schema: dict) -> str:
    s = get_settings()
    if not s.together_api_key:
        raise ProviderUnavailable("TOGETHER_API_KEY is not set")
    body = {
        "model": s.together_model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": 600,
        "response_format": {"type": "json_schema", "json_schema": {"name": "symptom_flags", "schema": schema}},
        "reasoning": {"enabled": False},
    }
    r = httpx.post(
        f"{s.together_url.rstrip('/')}/chat/completions",
        json=body,
        headers={"Authorization": f"Bearer {s.together_api_key}"},
        timeout=s.together_timeout,
    )
    r.raise_for_status()
    data = r.json()
    calllog.note(usage=data.get("usage"))
    return data["choices"][0]["message"]["content"] or ""


def _chat_ollama(messages: list[dict], schema: dict) -> str:
    s = get_settings()
    body = {"model": s.ollama_model, "messages": messages, "format": schema, "stream": False,
            "options": {"temperature": 0, "num_ctx": s.ollama_num_ctx}, "keep_alive": s.ollama_keep_alive}
    if s.ollama_think:
        body["think"] = s.ollama_think.lower() == "true"
    r = httpx.post(f"{s.ollama_url.rstrip('/')}/api/chat", json=body, timeout=s.llm_timeout)
    r.raise_for_status()
    data = r.json()
    calllog.note(usage={"prompt_tokens": data.get("prompt_eval_count"), "completion_tokens": data.get("eval_count")},
                 ollama_ms={k: round(data[k] / 1e6) for k in ("total_duration", "load_duration",
                                                              "prompt_eval_duration", "eval_duration") if data.get(k)})
    return data["message"]["content"]


_PROVIDERS = {"together": _chat_together, "ollama": _chat_ollama}


def _chat(messages: list[dict], schema: dict, provider: str) -> str:
    fn = _PROVIDERS.get(provider)
    if fn is None:
        raise ProviderUnavailable(f"unknown LLM provider: {provider}")
    return fn(messages, schema)


def _model_name(provider: str) -> str:
    s = get_settings()
    return {"together": s.together_model, "ollama": s.ollama_model}.get(provider, provider)


def _use_lexicon(provider: str) -> bool:
    mode = get_settings().lexicon_check.lower()
    return mode in ("always", "true") or (mode == "local" and provider == "ollama")


def provider_chain() -> list[str]:
    s = get_settings()
    chain = [s.llm_provider.lower()]
    if s.llm_fallback and s.llm_fallback.lower() not in chain:
        chain.append(s.llm_fallback.lower())
    return mode_chain("llm", chain)


def _parse(raw: str) -> dict[str, int]:
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()
    m = re.search(r"\{.*\}", raw, flags=re.S)
    if not m:
        raise ValueError("no JSON object in LLM output")
    return _model().model_validate(json.loads(m.group(0))).model_dump()


def extract_parameters(text: str, lang: str | None = None) -> Flags:
    """Return {symptom: -1/0/1} (a Flags dict; `.provider` says which model answered).

    For each provider in the chain (primary, then fallback): transient HTTP errors are retried
    (TOGETHER_RETRIES), invalid output is retried once, and any other failure moves on to the
    fallback. Raises ExtractionError when every provider failed.
    """
    if not text.strip():
        raise ExtractionError("empty transcript")
    messages = build_messages(text)
    schema = json_schema()
    retries = get_settings().together_retries
    last: Exception | None = None
    for provider in provider_chain():
        for attempt in range(2):  # invalid output -> retry once
            try:
                inputs = {"text": text, "language": lang, "attempt": attempt + 1}
                raw = with_retry(
                    lambda: calllog.record("llm", provider, _model_name(provider), inputs,
                                           lambda: _chat(messages, schema, provider), lambda r: {"raw": r}),
                    retries if provider == "together" else 0, f"llm/{provider}")
                parsed = _parse(raw)
                llm_flags = parsed
                if lang and _use_lexicon(provider):
                    # the small local model must have keyword support for every "yes" it reports
                    strict = lexicon.covered(lang) if provider == "ollama" else set()
                    parsed = lexicon.merge(parsed, lexicon.scan(text, lang), strict)
                calllog.write("extract", provider=provider, language=lang,
                              llm_flags={k: v for k, v in llm_flags.items() if v},
                              final_flags={k: v for k, v in parsed.items() if v},
                              lexicon_changed={k: [llm_flags.get(k), v] for k, v in parsed.items()
                                               if llm_flags.get(k) != v})
                flags = Flags(parsed)
                flags.provider = provider
                return flags
            except (ValidationError, ValueError, KeyError, IndexError) as e:
                last = e
                log.warning("llm/%s: invalid output (attempt %d): %s", provider, attempt + 1, type(e).__name__)
                calllog.write("extract", provider=provider, language=lang, ok=False,
                              error=f"invalid output: {type(e).__name__}: {e}"[:500])
            except (ProviderUnavailable, httpx.HTTPError) as e:
                last = e
                log.warning("llm/%s unavailable (%s), trying fallback", provider, type(e).__name__)
                break
    raise ExtractionError(str(last))
