"""Loads config files. Adding a language = edit languages.yaml + answers/<code>.json + audio + test sentences."""
import json
from functools import lru_cache

import yaml

from app.config import ANSWERS_DIR, CONFIG_DIR


def _load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache
def languages() -> dict[str, dict]:
    return _load_yaml("languages.yaml")["languages"]


@lru_cache
def default_language() -> str:
    return _load_yaml("languages.yaml")["default_language"]


@lru_cache
def symptoms() -> dict[str, str]:
    return _load_yaml("symptoms.yaml")["symptoms"]


@lru_cache
def profiles() -> dict[str, dict[str, int]]:
    return _load_yaml("profiles.yaml")["profiles"]


@lru_cache
def fewshot() -> dict[str, list[dict]]:
    path = CONFIG_DIR / "fewshot.yaml"
    if not path.exists():
        return {}
    return _load_yaml("fewshot.yaml")["examples"]


def conditions() -> list[str]:
    return list(profiles().keys())


@lru_cache
def answers(lang: str) -> dict[str, dict]:
    with open(ANSWERS_DIR / f"{lang}.json", encoding="utf-8") as f:
        return json.load(f)


def language_for_key(digit: str) -> str | None:
    for code, cfg in languages().items():
        if str(cfg["ivr_key"]) == str(digit):
            return code
    return None
