"""The synthetic eval set must be internally consistent: gold flags -> expected condition via the matcher."""
import yaml

from app.config import ROOT
from app.languages import languages, profiles, symptoms
from app.pipeline.match import match


def load():
    return yaml.safe_load((ROOT / "eval" / "extract_testset.yaml").read_text(encoding="utf-8"))["cases"]


def test_testset_covers_all_languages():
    cases = load()
    for lang in languages():
        assert len(cases.get(lang, [])) >= 10, lang


def test_gold_flags_give_expected_condition():
    kb = list(profiles().items())
    for lang, items in load().items():
        for it in items:
            assert set(it["flags"]) <= set(symptoms()), it["text"]
            params = {k: it["flags"].get(k, 0) for k in symptoms()}
            assert match(params, kb).result == it["condition"], f"{lang}: {it['text']}"
