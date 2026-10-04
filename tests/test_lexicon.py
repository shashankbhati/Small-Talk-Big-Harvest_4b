import json

import pytest

from app.languages import symptoms
from app.pipeline import extract, lexicon


@pytest.mark.parametrize("text,expected", [
    ("Kuna matundu madogo kwenye buni.", {"small_hole_in_berry": 1}),
    ("Hakuna matundu kwenye buni.", {"small_hole_in_berry": -1}),
    ("Majani hayana madoa ya njano.", {"yellow_spots_on_leaf": -1}),
    ("Majani yana unga wa rangi ya machungwa upande wa chini.", {"orange_powder_under_leaf": 1}),
    ("Hakuna unga wa machungwa.", {"orange_powder_under_leaf": -1}),
    ("Majani yanaanguka.", {"leaves_falling": 1}),
    ("Majani hayaanguki.", {"leaves_falling": -1}),
    ("Buni zinaanguka.", {"berries_falling_early": 1}),
    ("Mti unanyauka kwa sababu ya ukame.", {"wilting": 1, "wet_humid_weather": -1}),
    ("Mvua imenyesha sana wiki hizi.", {"wet_humid_weather": 1}),
    ("Mizizi ni myeusi na imeoza.", {"dark_soft_roots": 1}),
    ("Kuna wadudu wa kijani na majani yananata.", {"green_insects_on_leaves_stems": 1, "sticky_leaves": 1}),
    ("Kahawa iko sawa, hakuna wadudu.", {"green_insects_on_leaves_stems": -1, "insects_inside_berry": -1}),
    ("Hakuna madoa kwenye majani.", {"yellow_spots_on_leaf": -1, "brown_spot_grey_center": -1}),
    ("Hakuna madoa kwenye buni.", {}),  # berry spots: the generic leaf-spot rule must not fire
    ("Habari, nina swali tu.", {}),
])
def test_scan(text, expected):
    assert lexicon.scan(text, "sw") == expected


def test_negation_does_not_cross_clauses():
    # "hakuna" belongs to the first clause; the holes in the second clause are present
    assert lexicon.scan("Hakuna madoa, lakini kuna matundu kwenye buni.", "sw")["small_hole_in_berry"] == 1


def test_no_lexicon_for_language_is_noop():
    assert lexicon.scan("anything", "xx") == {}


def test_merge_rules():
    llm = {"a": 0, "b": 1, "c": -1, "d": 1, "e": 0}
    kw = {"a": 1, "b": 1, "c": 1, "d": 0}
    assert lexicon.merge(llm, kw) == {"a": 1, "b": 1, "c": 0, "d": 0, "e": 0}


def test_extract_fills_missed_symptom_and_resolves_conflict(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "lexicon_check", "always")
    llm_out = {k: 0 for k in symptoms()} | {"leaves_falling": 1}  # LLM missed holes, invented falling
    monkeypatch.setattr(extract, "_chat", lambda m, s, p=None: json.dumps(llm_out))
    flags = extract.extract_parameters("Kuna matundu kwenye buni, na majani hayaanguki.", "sw")
    assert flags["small_hole_in_berry"] == 1  # filled from keywords
    assert flags["leaves_falling"] == 0  # LLM yes vs keyword no -> unknown


def test_lexicon_can_be_disabled(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "lexicon_check", "off")
    monkeypatch.setattr(extract, "_chat", lambda m, s, p=None: json.dumps({k: 0 for k in symptoms()}))
    assert extract.extract_parameters("Kuna matundu kwenye buni.", "sw")["small_hole_in_berry"] == 0


def test_local_mode_applies_only_to_ollama(monkeypatch):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "lexicon_check", "local")
    monkeypatch.setattr(s, "llm_fallback", "ollama")
    empty = json.dumps({k: 0 for k in symptoms()})
    text = "Kuna matundu kwenye buni."

    monkeypatch.setattr(extract, "_chat", lambda m, sc, p=None: empty)  # together answers
    assert extract.extract_parameters(text, "sw")["small_hole_in_berry"] == 0

    def together_down(m, sc, p=None):
        if p == "together":
            raise extract.ProviderUnavailable("down")
        return empty

    monkeypatch.setattr(extract, "_chat", together_down)  # local fallback answers
    flags = extract.extract_parameters(text, "sw")
    assert flags.provider == "ollama" and flags["small_hole_in_berry"] == 1


def test_require_support_drops_unconfirmed_yes():
    llm = {"poor_growth_stunted": 1, "leaves_yellowing": 1, "wilting": 0}
    kw = {"leaves_yellowing": 1, "wilting": 1}
    out = lexicon.merge(llm, kw, {"poor_growth_stunted", "leaves_yellowing", "wilting"})
    assert out == {"poor_growth_stunted": 0, "leaves_yellowing": 1, "wilting": 1}


def test_invented_symptom_from_local_model_becomes_unknown(monkeypatch):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "lexicon_check", "local")
    monkeypatch.setattr(s, "llm_provider", "ollama")
    invented = {k: 0 for k in symptoms()} | {"leaves_yellowing": 1, "poor_growth_stunted": 1}
    monkeypatch.setattr(extract, "_chat", lambda m, sc, p=None: json.dumps(invented))
    flags = extract.extract_parameters("Mti unanyauka na majani yanageuka manjano.", "sw")
    assert flags["poor_growth_stunted"] == 0 and flags["wilting"] == 1 and flags["leaves_yellowing"] == 1
