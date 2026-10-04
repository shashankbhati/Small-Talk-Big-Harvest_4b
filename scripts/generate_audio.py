"""Generate PLACEHOLDER audio for every answers/<lang>.json entry, so the voice demo can <Play>.

Real deployments must replace these with recordings by native speakers.

    python scripts/generate_audio.py               # all languages, skip existing files
    python scripts/generate_audio.py --force --lang sw
    python scripts/generate_audio.py --clip sw "Majani yana unga..." out.mp3   # make a test clip

Engine: edge-tts (needs internet, only used offline-of-runtime to create static files).
Alternative fully-open option: MMS-TTS (facebook/mms-tts-swh / -ara / -hin, CC-BY-NC) via transformers.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

VOICES = {"sw": "sw-KE-ZuriNeural", "ar": "ar-EG-SalmaNeural", "hi": "hi-IN-SwaraNeural", "en": "en-US-JennyNeural"}


async def synth(text: str, voice: str, out: Path) -> None:
    import edge_tts

    out.parent.mkdir(parents=True, exist_ok=True)
    await edge_tts.Communicate(text, voice).save(str(out))


async def generate(langs: list[str], force: bool) -> None:
    for lang in langs:
        table = json.loads((ROOT / "answers" / f"{lang}.json").read_text(encoding="utf-8"))
        for key, entry in table.items():
            if not isinstance(entry, dict) or not entry.get("audio"):
                continue
            out = ROOT / "static" / "audio" / lang / entry["audio"]
            if out.exists() and not force:
                continue
            await synth(entry["text"], VOICES[lang], out)
            print(f"{lang}/{entry['audio']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", action="append")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--clip", nargs=3, metavar=("LANG", "TEXT", "OUT"))
    a = ap.parse_args()
    if a.clip:
        lang, text, out = a.clip
        asyncio.run(synth(text, VOICES[lang], Path(out)))
        return
    from app.languages import languages

    asyncio.run(generate(a.lang or list(languages()), a.force))


if __name__ == "__main__":
    main()
