# Small Talk

**A smallholder coffee farmer calls or texts from a basic phone, describes her coffee problem in her own language, and gets back a safe, human-written answer within minutes.**

> Because of Small Talk, a smallholder coffee farmer will know within minutes whether her coffee is sick and what to do, which she would otherwise learn months late or never. We know because coffee yields in East Africa have stagnated for decades (FAOSTAT), there is roughly one public extension officer per 1,000+ farm households in Kenya, and most rural farmers own a basic phone rather than a smartphone (GSMA). *(TODO team: add exact figures and links.)*

Hack-Nation × World Bank "Small AI for Development", Challenge 04, **Agriculture** track.

---

## How it works

The farmer speaks or texts in **Swahili, Arabic or Hindi** and gets one of three answers in that language:

| Answer | Example |
|---|---|
| ✅ **Healthy** | "Your coffee plant looks healthy." |
| 🩺 **Disease (sure)** | "Your plant likely has coffee leaf rust. Confidence: high. Remove badly infected leaves…" |
| ❓ **Not sure** | "We are not sure. The extension officer will call you." The case goes to a **human review queue**. |

Experts label the unsure cases. Verified labels are added to the knowledge base, so the next similar case gets a sure answer.

```
Farmer's phone (voice / SMS)
   → Twilio: language menu, consent menu, recording      [Africa's Talking in production]
   → FastAPI server
        1. Speech-to-text          Whisper large-v3 (Together)   → fallback: faster-whisper on the laptop
        2. Extract symptom flags   Qwen3.5-9B (Together)          → fallback: gemma3:4b via Ollama
                                   LLM output forced into a fixed JSON schema (24 symptoms, each yes/no/unknown)
        3. Match knowledge base    transparent score + margin rules (seed profiles + expert-verified cases)
        4. Answer                  pre-written text + pre-recorded audio in the farmer's language
   → SQLite (demo) / PostgreSQL;  audio in ./data/audio or MinIO, only with consent
   → Expert review page → verified case → knowledge base
```

## Why AI, and not a plain SMS menu?

A keypad menu can't capture *"majani yana unga wa machungwa chini na yanaanguka"* ("the leaves have orange powder underneath and are falling"). Speech recognition plus a small LLM turn **free speech in local languages into structured symptoms**. A simple, auditable rule-based matcher then makes the diagnosis. The AI only understands; it never decides what advice to give.

## Guardrails (pass/fail rules)

| Rule | How it is enforced |
|---|---|
| **The LLM never writes advice** | The LLM is only called in `app/pipeline/extract.py`, forced into a JSON schema (24 symptom keys, each `-1/0/1`) and validated with Pydantic. Every sentence the farmer hears or reads comes from human-written `answers/<lang>.json`. |
| **"Not sure" is a first-class outcome** | Reasons: `too_few_symptoms`, `weak_match`, `too_close`, `low_asr_confidence`, `extraction_failed`, `timeout`. Any error → "not sure". |
| **Only human-verified labels update the knowledge base** | Only the expert review form (`app/routes/review.py`) inserts `verified_case` rows. The system never learns from its own predictions. |
| **Privacy** | Consent at the start of the call (default: audio deleted after transcription). Phone numbers are hashed (SHA-256 + salt) and Fernet-encrypted only for the officer callback. The Twilio copy of the recording is deleted after download. Retention cleanup job; no phone numbers or transcripts in INFO logs (tested); the model call log (`MODEL_LOG_DIR`) does hold transcripts but never phone numbers, and is deleted after `RETENTION_DAYS` (set `MODEL_LOG_DIR=` to turn it off); IVR key `9` deletes all of the caller's data. |

## Models and hosting

| Step | Primary (hosted) | Fallback (local, tested on RTX 3050 Ti 4 GB / 14 GB RAM) |
|---|---|---|
| Speech-to-text | Together AI `openai/whisper-large-v3` | faster-whisper `large-v3-turbo`, int8 on GPU (CPU if the GPU fails) |
| Symptom extraction | Together AI `Qwen/Qwen3.5-9B` | Ollama `gemma3:4b` (~22 s per call) + Swahili keyword cross-check |

- Each hosted call is **retried once** on timeouts, rate limits or server errors. If it still fails, the **local model** takes over automatically. If that also fails, the farmer hears "not sure".
- Each case records which models answered it. `GET /health?deep=true` shows which backends are reachable. `python scripts/check_offline.py` simulates a Together outage.
- **Swahili keyword cross-check** (`config/lexicon/sw.yaml`): fills in Swahili farming words the models miss (*matundu*, *kunyauka*, *yananata*). It runs for both models (Qwen missed *matundu* after *unga wa machungwa*). For the local model it is also strict: a "yes" that no keyword confirms becomes "unknown". This removed a wrong diagnosis caused by gemma inventing a symptom.

> ⚠️ **Hosting note.** The challenge asks for *no paid cloud AI APIs*. This build uses Together AI by default: both models are **open-weights**, but Together is a **hosted, paid API**. To run fully on your own hardware, set `STT_PROVIDER=local` and `LLM_PROVIDER=ollama`. No code changes are needed; the local stack was tested end to end (see results).

## Knowledge base

Source: `knowledge/coffee_disease_knowledge_base.xlsx` (team-provided), converted into `config/symptoms.yaml` (24 symptoms), `config/profiles.yaml` and the advice in `answers/*.json`.

| Condition | Cause | Key signs the farmer may mention |
|---|---|---|
| Coffee leaf rust | *Hemileia vastatrix* | yellow spots on top, orange powder underneath, leaves falling |
| Coffee berry disease | *Colletotrichum kahawae* | dark sunken spots on green berries, berries shrivel and fall, wet weather |
| Coffee wilt disease | *Fusarium xylarioides* | wilting, dry leaves stay attached, branch dieback, dark wood inside the stem |
| Brown eye spot | *Cercospora* spp. | round brown spots with a grey centre and dark border |
| Root rot | soil-borne fungi | poor growth, yellowing, wilting, dark soft roots, waterlogged soil |
| Coffee berry borer | *Hypothenemus hampei* | tiny hole in the berry, insects or tunnels inside |
| Green coffee scale | *Coccus viridis* | small green insects on leaves and stems, sticky leaves, black sooty mould, ants |
| Coffee berry rot | various fungi | soft, rotten, mouldy berries after long rain |

Safety change from the workbook: it says to destroy *confirmed* wilt trees, but a phone diagnosis is only "likely". So the answer says *call the officer to confirm before removing the tree*.

## Quick start

Requirements: Python 3.11+, `ffmpeg` on PATH. Optional for the local fallback: an NVIDIA GPU, and [Ollama](https://ollama.com) with `ollama pull gemma3:4b`.

```bash
python -m venv .venv
.venv\Scripts\activate                 # Windows   (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
cp .env.example .env                   # set TOGETHER_API_KEY, FERNET_KEY, PHONE_SALT, REVIEW_PASSWORD
python scripts/seed_db.py              # 9 profiles: 8 conditions + healthy
python scripts/generate_audio.py       # optional: placeholder audio (replace with native recordings)
uvicorn app.main:app --port 8000
# other devices on your network: uvicorn app.main:app --host 0.0.0.0 --port 8000  (link printed at startup)
```

| What | Where |
|---|---|
| Browser demo (no phone needed): mic, upload or text | http://localhost:8000/demo |
| Expert review queue (basic auth) | http://localhost:8000/review |
| Command line | `python scripts/demo_cli.py --lang sw --text "Majani yana unga wa machungwa chini"` or `--audio clip.wav` |
| Tests (87) | `pytest` |

### Phone and SMS (Twilio + ngrok)
1. `ngrok http 8000`, then set `PUBLIC_BASE_URL=https://<id>.ngrok.app` in `.env` and restart.
2. In the Twilio console: Voice webhook `POST {PUBLIC_BASE_URL}/voice/incoming`, Messaging webhook `POST {PUBLIC_BASE_URL}/sms/incoming`.
3. Set `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN`. Keep `TWILIO_VALIDATE=true` (every webhook's signature is checked).

**Call flow:** welcome (3 Hindi · 9 delete my data) → beep right after the key press, describe (up to 30 s; audio is used for this answer only, then deleted) → "please wait" while processing runs in the background (the call checks every 3 s, up to ~5 min, `VOICE_MAX_TRIES`) → answer → goodbye.

### Farmer registry (registration app)
A family member registers the farm once in the web app; after that a plain phone call from that number is matched to the farm.

| Endpoint | What it does |
|---|---|
| `POST /api/farmers` | `{phone, lat, lon, place, crops, area_acres, consent}` → `{token}`. Location is rounded to ~1 km; a typed village is geocoded. |
| `GET /api/farmers/me/cases` | Answers given on calls since registration (`Authorization: Bearer <token>`). Same human-written text as the call; an expert's label replaces a "not sure". |
| `PUT /api/farmers/me` · `DELETE /api/farmers/me` | Change details · delete the registration and all cases. |

- A registered caller **skips the language menu** (`FARMER_LANGUAGE`, default `hi`) and the case gets the farm location, so **weather is used on phone calls** too.
- Stored: phone hash, token hash, rounded location, crops, field size. Key `9` on the call deletes the registration as well.
- **Limit:** there is no SMS code check. Registering a number again issues a new token and hides earlier cases, but a real service needs to verify the number.

**SMS:** language from the prefix (`SW`, `AR`, `HI`) or from the script (Arabic → ar, Devanagari → hi, otherwise sw). The first reply includes a one-line privacy notice.

**Retention:** run `python scripts/cleanup.py` daily. It deletes cases past `delete_after` (default 365 days) with their audio, and any leftover "answer only" audio, and model call logs older than `RETENTION_DAYS`.

## Configuration (main `.env` settings)

| Setting | Default | Meaning |
|---|---|---|
| `STT_PROVIDER` / `STT_FALLBACK` | `together` / `local` | speech-to-text backend and its fallback |
| `LLM_PROVIDER` / `LLM_FALLBACK` | `together` / `ollama` | extraction backend and its fallback |
| `TOGETHER_RETRIES`, `TOGETHER_TIMEOUT` | `1`, `10` s | retry policy before falling back |
| `WHISPER_MODEL`, `WHISPER_DEVICE` | `large-v3-turbo`, `cuda` | local Whisper |
| `OLLAMA_MODEL`, `OLLAMA_NUM_CTX` | `gemma3:4b`, `8192` | local LLM (the prompt is ~4.3k tokens) |
| `WEATHER_ENABLED` | `true` | past weather at the farm nudges the match (Open-Meteo, no API key); rules in `config/weather.yaml` |
| `MODEL_LOG_DIR` | `./data/logs` | JSON-lines log of every STT/LLM call (provider, model, mode, input, output, latency, tokens, errors) and every case (`model_calls-YYYY-MM-DD.jsonl`); empty = off |
| `LEXICON_CHECK` | `always` | keyword cross-check: `always`, `local` (only the local model) or `off` |
| `MIN_KNOWN`, `SCORE_MIN`, `MARGIN_MIN` | `2`, `0.75`, `0.15` | when to say "not sure" |
| `ASR_MIN_CONF` | `0.45` | low speech-recognition confidence → "not sure" |
| `VOICE_MAX_TRIES` | `25` | call waits ~75 s before "not sure" |
| `RETENTION_DAYS` | `365` | automatic deletion |

## Weather reasoning (demo page)

The demo page takes a farm location: **📍 Use my location** (browser GPS) or a typed village/town, which is
looked up with Open-Meteo geocoding. Coordinates are rounded to 2 decimals (~1 km) before they are stored or sent.

1. Open-Meteo returns the last 60 days of daily rain, temperature and humidity (free, no API key).
2. `app/pipeline/weather.py` turns them into facts per window (14/21/30/42/60 days): rain mm, rainy days,
   very humid days, hot days, warm-wet days, longest wet/dry spell, mean temperature.
3. Rules in `config/weather.yaml` give each condition a weather score with plain-language reasons
   (e.g. *"12 warm rainy days (18-26 °C) in the last 6 weeks — rust spores need wet leaves and warmth"*).
   Diseases show up weeks after the weather that caused them, so each rule looks at its own window.
4. The matcher adds at most `max_bonus` (0.1) to the symptom score. "Weak match" still uses the symptom
   score alone and weather never counts as a symptom, so weather breaks ties but never answers by itself.
5. The daily data, facts, risks and reasons are stored on the case (`cases.weather`) and shown on the demo
   result and the review page. Weather and geocoding calls are in the model call log. If the weather
   service is down, the case is answered without weather.

The thresholds in `config/weather.yaml` are a **draft** and need agronomist review.

## How matching works

1. Keep only the symptoms the farmer actually mentioned (yes or no). Fewer than 2 → **not sure** (`too_few_symptoms`).
2. Score each profile: **1.0** when it agrees, **0.5** when the farmer says "no" to a symptom the condition doesn't involve, **0** for an unexplained or contradicting symptom. Average over the mentioned symptoms.
3. A condition's score is its best row (seed profile or any expert-verified case).
4. Best score below 0.75 → **not sure** (`weak_match`). Top two within 0.15 → **not sure** (`too_close`). Otherwise → the best condition.

## Results

Synthetic test set: 12 sentences per language (8 conditions, healthy, 3 cases that should get "not sure"), tested as text and as speech, with the hosted and the local model stack. **The hosted stack made no wrong diagnosis. The local stack made one** (Hindi speech: a misheard word led gemma to invent a symptom; Hindi has no keyword list yet). All other misses were honest "not sure" answers. Live scenarios: 13/13 passed; unit tests: 87 passed.

<!-- RESULTS:START -->
**Speech end to end: synthetic audio of the 36 test sentences → speech-to-text → extraction → diagnosis. Low `wrong` matters more than high `correct`.**

| stack | lang | n | correct | wrong | not_sure | mean_asr_conf | sec_per_case |
|---|---|---|---|---|---|---|---|
| openai/whisper-large-v3 + Qwen/Qwen3.5-9B | sw | 12 | 92% | 0% | 8% | 0.9 | 3.8 |
| openai/whisper-large-v3 + Qwen/Qwen3.5-9B | ar | 12 | 100% | 0% | 0% | 0.98 | 5.7 |
| openai/whisper-large-v3 + Qwen/Qwen3.5-9B | hi | 12 | 83% | 0% | 17% | 0.97 | 8.8 |
| large-v3-turbo (local) + gemma3:4b (local) | sw | 12 | 92% | 0% | 8% | 0.87 | 23.0 |
| large-v3-turbo (local) + gemma3:4b (local) | ar | 12 | 83% | 0% | 17% | 0.94 | 23.0 |
| large-v3-turbo (local) + gemma3:4b (local) | hi | 12 | 92% | 8% | 0% | 0.94 | 23.2 |

**Text end to end: test sentence → extraction → diagnosis (also what SMS does).**

| provider | model | lang | n | correct | wrong | not_sure |
|---|---|---|---|---|---|---|
| ollama | gemma3:4b | sw | 12 | 100% | 0% | 0% |
| ollama | gemma3:4b | ar | 12 | 83% | 0% | 17% |
| ollama | gemma3:4b | hi | 12 | 83% | 0% | 17% |
| together | Qwen/Qwen3.5-9B | sw | 12 | 92% | 0% | 8% |
| together | Qwen/Qwen3.5-9B | ar | 12 | 100% | 0% | 0% |
| together | Qwen/Qwen3.5-9B | hi | 12 | 100% | 0% | 0% |

**Symptom extraction: how many of the 24 symptom flags the LLM got right.**

| provider | model | lang | n | exact_match | symptom_accuracy | failed | sec_per_case |
|---|---|---|---|---|---|---|---|
| ollama | gemma3:4b | sw | 12 | 92% | 100% | 0 | 22.23 |
| ollama | gemma3:4b | ar | 12 | 58% | 97% | 0 | 22.29 |
| ollama | gemma3:4b | hi | 12 | 58% | 96% | 0 | 22.41 |
| together | Qwen/Qwen3.5-9B | sw | 12 | 75% | 93% | 0 | 2.91 |
| together | Qwen/Qwen3.5-9B | ar | 12 | 92% | 99% | 0 | 2.85 |
| together | Qwen/Qwen3.5-9B | hi | 12 | 92% | 94% | 0 | 3.26 |

**Speech recognition on FLEURS (25 real read-speech clips per language): word error rate (lower is better).**

| provider | model | lang | fleurs | n | wer | mean_asr_conf | below_min_conf | sec_per_clip |
|---|---|---|---|---|---|---|---|---|
| local | small | sw | sw_ke | 25 | 0.739 | 0.519 | 2 | 8.58 |
| local | small | ar | ar_eg | 25 | 0.232 | 0.774 | 0 | 7.41 |
| local | small | hi | hi_in | 25 | 0.343 | 0.685 | 1 | 13.47 |
| together | openai/whisper-large-v3 | sw | sw_ke | 25 | 0.326 | 0.867 | 0 | 1.48 |
| together | openai/whisper-large-v3 | ar | ar_eg | 25 | 0.078 | 0.969 | 0 | 1.32 |
| together | openai/whisper-large-v3 | hi | hi_in | 25 | 0.237 | 0.878 | 2 | 1.68 |
| local | large-v3-turbo | sw | sw_ke | 25 | 0.347 | 0.804 | 1 | 1.21 |
| local | large-v3-turbo | ar | ar_eg | 25 | 0.076 | 0.94 | 0 | 1.06 |
| local | large-v3-turbo | hi | hi_in | 25 | 0.151 | 0.92 | 0 | 1.74 |

Full report, including live scenarios and findings: [`eval/RESULTS.md`](eval/RESULTS.md).
<!-- RESULTS:END -->

Run them yourself: `python scripts/eval_asr.py`, `python scripts/eval_extract.py` (extraction + end-to-end), then `python scripts/report.py` to update this section.

## Data sources and licenses

| Item | Source | License |
|---|---|---|
| Disease knowledge base | `knowledge/coffee_disease_knowledge_base.xlsx` (team). **TODO: add citations** (e.g. CABI PlantwisePlus, KALRO / Coffee Research Institute) | — |
| Speech-recognition eval audio | FLEURS (`google/fleurs`: sw_ke, ar_eg, hi_in) | CC-BY-4.0 |
| Future speech fine-tuning | Mozilla Common Voice | CC0 |
| Test set, few-shot examples, Swahili keyword list | **Synthetic**, written by the team | ours |
| Prompt audio | Placeholder, generated with edge-tts; **replace with native-speaker recordings** | demo only |

**Models:** Whisper large-v3 / large-v3-turbo (MIT) · Qwen3.5-9B (Apache-2.0) · Gemma 3 (Gemma Terms of Use).

## What the data does not cover (limits)

- **Only 8 conditions.** Anything else (Phoma, leaf miner, nutrient deficiency, drought stress…) gets "not sure".
- The knowledge base **has no citations and is not agronomist-validated** yet.
- Translations, advice texts and the Swahili keyword list are **drafts**. A native speaker and an agronomist must check them before recording.
- **No real farmer recordings yet.** Tests use FLEURS (clean read speech) and sentences we wrote ourselves, partly after building the keyword list, so real-world accuracy will be lower. Phone audio (8 kHz, noise) is harder.
- Whisper is weaker in Swahili and **does not support Kikuyu**.
- **Arabic dialects** in coffee regions differ from the Egyptian Arabic in FLEURS.
- **Look-alikes** give "not sure" unless a distinguishing sign is mentioned: wilt vs root rot, drying/falling berries, yellowing with leaf drop. The workbook's follow-up questions could be asked by the IVR in a later version.
- The local fallback is slower (~22 s per LLM call). A phone answer can take up to ~75 s when Together is down.

## Add a language (no code changes)

1. `config/languages.yaml`: name, IVR key, Whisper code, SMS prefix, script.
2. `answers/xx.json`: same keys as `answers/en.json` (a test checks that every condition exists).
3. `static/audio/xx/`: native-speaker recordings.
4. `config/fewshot.yaml` (2 examples) and `eval/extract_testset.yaml` (~12 sentences).
5. Optional: `config/lexicon/xx.yaml` keyword list (makes the local fallback safer).

## Project layout

```
app/          FastAPI app: config, db, models, storage, privacy, health
  pipeline/   stt, extract, lexicon, match, answer, run, resilience (retry + fallback)
  routes/     voice, sms, review, demo
config/       languages, symptoms, profiles, fewshot, lexicon/
answers/      en (master), sw, ar, hi
knowledge/    coffee disease knowledge base (xlsx)
static/audio/ prompts and answers per language
scripts/      seed_db, demo_cli, generate_audio, cleanup, check_offline, eval_*, report
eval/         test set and results (CSV)
tests/        pytest suite
```

**Out of scope:** image diagnosis, prices, farmer registry, production deployment, multi-tenant auth.
