"""Rule-based matching of extracted symptoms against the knowledge base (seed + verified cases)."""
from dataclasses import dataclass, field
from typing import Iterable

from app.config import get_settings

NOT_SURE = "not_sure"


@dataclass
class MatchResult:
    result: str
    score: float | None
    top2: list = field(default_factory=list)
    not_sure_reason: str | None = None

    @property
    def sure(self) -> bool:
        return self.result != NOT_SURE


def _pts(p: int, v: int) -> float:
    if p == v:
        return 1.0
    if p == 0 and v == -1:
        return 0.5
    return 0.0  # p == 0 and v == 1, or contradiction


def score(profile: dict, known: dict) -> float:
    return sum(_pts(int(profile.get(f, 0)), v) for f, v in known.items()) / len(known)


def match(params: dict[str, int], profiles: Iterable[tuple[str, dict]],
          weather_bonus: dict[str, float] | None = None) -> MatchResult:
    """profiles: iterable of (condition, vector) — all knowledge_profiles rows.

    weather_bonus: {condition: small +/- value} from past weather. It is added to the symptom score for
    ranking and the margin check, but "weak match" still uses the symptom score alone, and weather never
    counts as a symptom — so weather can break a tie but never make an answer by itself.
    """
    weather_bonus = weather_bonus or {}
    s = get_settings()
    known = {f: int(v) for f, v in params.items() if int(v) != 0}
    if len(known) < s.min_known:
        return MatchResult(NOT_SURE, None, [], "too_few_symptoms")

    cond_score: dict[str, float] = {}
    for cond, vec in profiles:
        sc = score(vec, known)
        if sc > cond_score.get(cond, -1.0):
            cond_score[cond] = sc
    adjusted = {c: v + weather_bonus.get(c, 0.0) for c, v in cond_score.items()}
    ranked = sorted(adjusted.items(), key=lambda kv: kv[1], reverse=True)
    if not ranked:
        return MatchResult(NOT_SURE, None, [], "weak_match")
    top2 = [[c, round(v, 3)] for c, v in ranked[:2]]
    c1, s1 = ranked[0]
    s2 = ranked[1][1] if len(ranked) > 1 else 0.0

    if cond_score[c1] < s.score_min:
        return MatchResult(NOT_SURE, round(s1, 3), top2, "weak_match")
    if s1 - s2 < s.margin_min:
        return MatchResult(NOT_SURE, round(s1, 3), top2, "too_close")
    return MatchResult(c1, round(s1, 3), top2, None)
