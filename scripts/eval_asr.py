"""ASR word error rate on FLEURS (sw_ke, ar_eg, hi_in) with the configured Whisper model.

    python scripts/eval_asr.py [--n 25]

Downloads FLEURS test clips from the Hugging Face hub (google/fleurs, CC-BY-4.0) the first time.
Writes eval/asr_results.csv.
"""
import argparse
import csv
import io
import re
import sys
import tempfile
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import get_settings  # noqa: E402
from app.pipeline.stt import transcribe  # noqa: E402

FLEURS = {"sw": "sw_ke", "ar": "ar_eg", "hi": "hi_in"}


def normalize(t: str) -> str:
    t = unicodedata.normalize("NFKC", t).lower()
    t = re.sub(r"[ً-ْ]", "", t)  # Arabic diacritics
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def fleurs_samples(config: str, n: int):
    """Yield (audio_bytes_wav, transcription) from FLEURS test split."""
    from huggingface_hub import hf_hub_download
    import tarfile

    tsv = hf_hub_download("google/fleurs", f"data/{config}/test.tsv", repo_type="dataset")
    tar = hf_hub_download("google/fleurs", f"data/{config}/audio/test.tar.gz", repo_type="dataset")
    rows = {}
    with open(tsv, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 3:
                rows[parts[1]] = parts[2]  # file name -> raw transcription
    out = 0
    with tarfile.open(tar, "r:gz") as tf:
        for m in tf:
            name = Path(m.name).name
            if not m.isfile() or name not in rows:
                continue
            yield tf.extractfile(m).read(), rows[name]
            out += 1
            if out >= n:
                return


def main() -> None:
    import jiwer

    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=25)
    a = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    s = get_settings()
    model = s.together_stt_model if s.stt_provider == "together" else s.whisper_model
    results = []
    for lang, cfg in FLEURS.items():
        refs, hyps, confs, t0 = [], [], [], time.time()
        for wav, ref in fleurs_samples(cfg, a.n):
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(wav)
            text, _det, conf = transcribe(tmp.name, lang)
            Path(tmp.name).unlink(missing_ok=True)
            refs.append(normalize(ref))
            hyps.append(normalize(text) or "<empty>")
            if conf is not None:
                confs.append(conf)
        wer = jiwer.wer(refs, hyps)
        row = {"provider": s.stt_provider, "model": model, "lang": lang, "fleurs": cfg, "n": len(refs),
               "wer": round(wer, 3),
               "mean_asr_conf": round(sum(confs) / len(confs), 3) if confs else "n/a",
               "below_min_conf": sum(c < s.asr_min_conf for c in confs) if confs else "n/a",
               "sec_per_clip": round((time.time() - t0) / len(refs), 2)}
        results.append(row)
        print(row)

    # keep results of other models; replace rows for this one
    out = ROOT / "eval" / "asr_results.csv"
    old = []
    if out.exists():
        old = [r for r in csv.DictReader(out.open(encoding="utf-8")) if r.get("model") != model]
        for r in old:
            r.setdefault("provider", "local")
            r["provider"] = r.get("provider") or "local"
    rows = old + results
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0]), extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    main()
