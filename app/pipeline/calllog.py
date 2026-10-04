"""Model call log: one JSON line per model call (STT / LLM, every attempt) and one per finished case.

Written to MODEL_LOG_DIR/model_calls-YYYY-MM-DD.jsonl (empty MODEL_LOG_DIR = off). Each line has the
provider, model, mode (together | local | env), input, output, latency_ms, ok/error and the case id,
so Together AI and local runs can be compared side by side. Phone numbers are never logged.
Files older than RETENTION_DAYS are removed by scripts/cleanup.py.
"""
import json
import logging
import threading
import time
from contextvars import ContextVar
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar

from app.config import ROOT, get_settings
from app.pipeline.resilience import model_mode

log = logging.getLogger(__name__)
T = TypeVar("T")

current_case: ContextVar[str | None] = ContextVar("current_case", default=None)
_extra: ContextVar[dict | None] = ContextVar("calllog_extra", default=None)
_lock = threading.Lock()


def log_dir() -> Path | None:
    d = get_settings().model_log_dir
    if not d:
        return None
    p = Path(d)
    return p if p.is_absolute() else ROOT / p


def write(event: str, **fields: Any) -> None:
    """Append one JSON line. Never raises: logging must not break a farmer's answer."""
    d = log_dir()
    if d is None:
        return
    row = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "event": event,
           "case_id": current_case.get(), "mode": model_mode.get() or "env", **fields}
    try:
        d.mkdir(parents=True, exist_ok=True)
        line = json.dumps(row, ensure_ascii=False, default=str)
        with _lock, open(d / f"model_calls-{date.today().isoformat()}.jsonl", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        log.exception("could not write model call log")


def note(**fields: Any) -> None:
    """Add details (token usage, durations, ...) to the model call that is running now."""
    extra = _extra.get()
    if extra is not None:
        extra.update(fields)


def record(kind: str, provider: str, model: str, inputs: dict, call: Callable[[], T],
           output: Callable[[T], dict]) -> T:
    """Run one model call, timing it and logging input, output (or error) and latency."""
    extra: dict = {}
    token = _extra.set(extra)
    t0 = time.perf_counter()
    try:
        result = call()
    except Exception as e:
        ms = round((time.perf_counter() - t0) * 1000)
        log.info("%s/%s FAILED in %d ms: %s", kind, provider, ms, type(e).__name__)
        write(kind, provider=provider, model=model, ok=False, latency_ms=ms, input=inputs,
              error=f"{type(e).__name__}: {e}"[:500], **extra)
        raise
    finally:
        _extra.reset(token)
    ms = round((time.perf_counter() - t0) * 1000)
    out = output(result)
    log.info("%s/%s ok in %d ms", kind, provider, ms)
    write(kind, provider=provider, model=model, ok=True, latency_ms=ms, input=inputs, output=out, **extra)
    return result


def cleanup(older_than_days: int, today: date | None = None) -> int:
    """Delete log files older than `older_than_days`. Returns how many were removed."""
    d = log_dir()
    if d is None or not d.exists():
        return 0
    today = today or date.today()
    removed = 0
    for f in d.glob("model_calls-*.jsonl"):
        try:
            day = date.fromisoformat(f.stem.removeprefix("model_calls-"))
        except ValueError:
            continue
        if (today - day).days > older_than_days:
            f.unlink(missing_ok=True)
            removed += 1
    return removed
