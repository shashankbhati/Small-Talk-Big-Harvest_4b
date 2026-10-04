"""Keyword cross-check for LLM symptom extraction (config/lexicon/<lang>.yaml, human-written).

It never adds advice; it only adjusts symptom flags, and on any disagreement it falls back to 0 (unknown),
which pushes the matcher towards "not sure".
"""
import logging
import re
from functools import lru_cache

import yaml

from app.config import CONFIG_DIR

log = logging.getLogger(__name__)


@lru_cache
def load(lang: str) -> dict | None:
    path = CONFIG_DIR / "lexicon" / f"{lang}.yaml"
    if not path.exists():
        return None
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    flags = re.IGNORECASE | re.UNICODE
    return {
        "negators": {n.lower() for n in cfg.get("negators", [])},
        "window": int(cfg.get("negation_window", 4)),
        "split": re.compile(cfg.get("clause_split", r"[.;!?,]"), flags),
        "yes": {s: [re.compile(p, flags) for p in v.get("present", [])] for s, v in cfg["symptoms"].items()},
        "no": {s: [re.compile(p, flags) for p in v.get("absent", [])] for s, v in cfg["symptoms"].items()},
        "generic": {w.lower(): _generic_rule(r) for w, r in (cfg.get("negated_generic") or {}).items()},
    }


def _generic_rule(rule) -> dict:
    """`word: [symptoms]` or `word: {symptoms: [...], unless: [...]}`."""
    if isinstance(rule, list):
        return {"symptoms": rule, "unless": set()}
    return {"symptoms": rule["symptoms"], "unless": {u.lower() for u in rule.get("unless", [])}}


def _negated(clause: str, start: int, lex: dict) -> bool:
    before = re.findall(r"\w+", clause[:start].lower())[-lex["window"]:]
    return any(w in lex["negators"] for w in before)


def scan(text: str, lang: str) -> dict[str, int]:
    """Return only the symptoms the keywords found: {symptom: 1 or -1}. Conflicting hits -> 0."""
    lex = load(lang)
    if lex is None:
        return {}
    found: dict[str, set[int]] = {}
    for clause in lex["split"].split(text):
        if not clause or not clause.strip():
            continue
        for sym, pats in lex["no"].items():
            if any(p.search(clause) for p in pats):
                found.setdefault(sym, set()).add(-1)
        spans = []  # specific matches; a generic word inside one is not generic ("madoa ya njano")
        for sym, pats in lex["yes"].items():
            for p in pats:
                m = p.search(clause)
                if m:
                    spans.append(m.span())
                    found.setdefault(sym, set()).add(-1 if _negated(clause, m.start(), lex) else 1)
                    break
        words = list(re.finditer(r"\w+", clause.lower()))
        for i, wm in enumerate(words):
            w = wm.group(0)
            rule = lex["generic"].get(w)
            if rule is None or any(a <= wm.start() < b for a, b in spans):
                continue
            clause_words = {x.group(0) for x in words}
            if rule["unless"] & clause_words:
                continue
            if any(x.group(0) in lex["negators"] for x in words[max(0, i - lex["window"]):i]):
                for sym in rule["symptoms"]:
                    found.setdefault(sym, set()).add(-1)
    return {s: (next(iter(v)) if len(v) == 1 else 0) for s, v in found.items()}


def covered(lang: str) -> set[str]:
    """Symptoms the lexicon has `present` patterns for (it can confirm or reject an LLM 'yes')."""
    lex = load(lang)
    return {s for s, pats in lex["yes"].items() if pats} if lex else set()


def merge(llm: dict[str, int], kw: dict[str, int], require_support: set[str] = frozenset()) -> dict[str, int]:
    """LLM said 0 -> keyword value; agree -> keep; disagree -> 0 (unknown, never guess).

    require_support: symptoms where an LLM 'yes' without any keyword hit is downgraded to 0
    (used for the small local model, which sometimes invents symptoms).
    """
    out = dict(llm)
    for sym in require_support:
        if out.get(sym) == 1 and sym not in kw:
            out[sym] = 0
    for sym, v in kw.items():
        if sym not in out:
            continue
        if out[sym] == 0:
            out[sym] = v
        elif v != 0 and v != out[sym]:
            out[sym] = 0
        elif v == 0:  # keywords themselves were contradictory
            out[sym] = 0
    return out
