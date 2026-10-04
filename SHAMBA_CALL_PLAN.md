# Shamba Call — Implementation Plan

> Hand this file to Claude Code: *"Read SHAMBA_CALL_PLAN.md and implement it milestone by milestone. Run the tests and the acceptance check at the end of each milestone before moving on."*

## 0. What we are building

**Shamba Call** lets a smallholder coffee farmer **call a phone number (or send an SMS) from a basic phone**, describe her coffee problem **in her own language**, and get back one of three answers in that language:

1. **Healthy**: "Your coffee plant looks healthy."
2. **Disease (sure)**: "Your plant likely has coffee leaf rust. Confidence: high. Do this: …"
3. **Not sure**: "We are not sure. The extension officer will call you." The case goes to a **human review queue**.

Human experts label the unsure cases. Verified labels are added to the **knowledge base**, so the next similar case gets a sure answer.

Context: Hack-Nation × World Bank "Small AI for Development" hackathon, Challenge 04, **Agriculture** track. The submission deadline is the end of **Sunday 4 Oct 2026**, so check the exact time on the Hack-Nation site. **Build demo-first:** a working end-to-end demo beats a complete but broken system.

### Languages (v1)
| Code | Language | IVR key |
|---|---|---|
| `sw` | Swahili | 1 |
| `ar` | Arabic | 2 |
| `hi` | Hindi | 3 |

Adding a language must only require: a config entry, answer texts and audio, and test sentences. **No code changes.**

### Non-negotiable rules (the judges check these as pass/fail)
- **The LLM never writes advice.** It only extracts symptoms into a fixed JSON schema. Every sentence the farmer hears or reads comes from `answers/*.json`, which humans wrote.
- **"Not sure" is a first-class outcome.** When in doubt, never guess.
- **Only human-verified labels update the knowledge base.** The system never learns from its own predictions.
- **No paid cloud AI APIs.** All models are open source and run on our own server (Small AI).
- **Privacy:** consent at the start of the call, phone numbers hashed and encrypted, audio deleted when there is no consent, and automatic retention cleanup.

---

## 1. Architecture

```
Farmer's phone (voice / SMS)
   → Twilio (consent menu + recording)            [Africa's Talking in production]
   → FastAPI server (self-hosted)
        1. Speech-to-text + language   (faster-whisper; MMS optional)
        2. LLM extracts parameters     (Ollama, JSON schema enforced)
        3. Match with knowledge DB     (score + margin)
        4. Answer in her language      (pre-written text + pre-recorded audio)
   → storage:
        audio  → local folder (demo) / MinIO (prod)          [only if consent = keep]
        cases, knowledge base, review queue → SQLite (demo) / PostgreSQL (prod)
   → Expert review page: listen, label, correct → verified case → knowledge base
   → answer goes back to the farmer (voice: TwiML <Play>, SMS: reply text)
```

---

## 2. Tech stack

| Concern | Choice |
|---|---|
| Language/runtime | Python 3.11+ |
| Web | FastAPI + Uvicorn, Jinja2 templates for the review page |
| DB | SQLAlchemy 2.x. **SQLite by default**, PostgreSQL via `DATABASE_URL` (same code) |
| Audio storage | `Storage` interface with a `LocalStorage` default (`./data/audio`). `MinioStorage` is optional, chosen via env |
| Speech-to-text | `faster-whisper`. Model from env (`WHISPER_MODEL`, default `small`; use `large-v3-turbo` if a GPU is available) |
| LLM | Ollama HTTP API. Model from env (`OLLAMA_MODEL`, default `gemma3:4b`, fallback `qwen2.5:3b`), using the `format` parameter with a JSON schema |
| Telephony | Twilio Voice + SMS webhooks (TwiML), `twilio` Python SDK |
| Audio conversion | `ffmpeg` (wav → Opus `.ogg`, mono, 16 kHz) |
| Crypto | `cryptography` (Fernet) for the encrypted phone number; SHA-256 + salt for the phone hash |
| Tests | `pytest`, `httpx` TestClient |
| Eval | `jiwer` (word error rate), `datasets` (FLEURS samples) |
| Local tunnel | `ngrok`, so Twilio can reach the laptop |

---

## 3. Repository layout

```
shamba-call/
├─ README.md
├─ .env.example
├─ pyproject.toml            # or requirements.txt
├─ app/
│  ├─ main.py                # FastAPI app, routers
│  ├─ config.py              # pydantic-settings, reads .env
│  ├─ languages.py           # loads config/languages.yaml
│  ├─ db.py                  # engine, session, init_db()
│  ├─ models.py              # SQLAlchemy models
│  ├─ storage.py             # Storage interface, LocalStorage, MinioStorage
│  ├─ privacy.py             # hash_phone, encrypt/decrypt phone
│  ├─ pipeline/
│  │  ├─ stt.py              # transcribe(audio_path, lang_hint) -> (text, lang, asr_conf)
│  │  ├─ extract.py          # extract_parameters(text, lang) -> dict[str,int]
│  │  ├─ match.py            # match(params, profiles, verified_cases) -> MatchResult
│  │  ├─ answer.py           # render_answer(result, lang) -> Answer(text, audio_url)
│  │  └─ run.py              # run_case(case_id): orchestrates 1→4, writes DB
│  ├─ routes/
│  │  ├─ voice.py            # Twilio voice webhooks
│  │  ├─ sms.py              # Twilio SMS webhook
│  │  ├─ review.py           # expert review page (basic auth)
│  │  └─ demo.py             # /demo upload page (no Twilio needed)
│  └─ templates/             # review_list.html, review_case.html, demo.html
├─ config/
│  ├─ languages.yaml
│  ├─ symptoms.yaml          # the fixed symptom schema
│  └─ profiles.yaml          # seed disease profiles (knowledge base)
├─ answers/
│  ├─ sw.json  ar.json  hi.json
├─ static/audio/{sw,ar,hi}/  # pre-recorded prompts and answers (.mp3 or .wav)
├─ scripts/
│  ├─ seed_db.py             # load profiles.yaml into DB
│  ├─ demo_cli.py            # run pipeline on a local audio file or text
│  ├─ generate_audio.py      # placeholder audio via MMS-TTS (optional)
│  ├─ cleanup.py             # retention deletion job
│  ├─ eval_asr.py            # WER on FLEURS sw/ar/hi
│  └─ eval_extract.py        # extraction accuracy on test sentences
└─ tests/
```

---

## 4. Configuration files

### 4.1 `config/languages.yaml`
```yaml
languages:
  sw: { name: Swahili, ivr_key: "1", whisper_code: sw, twilio_say_voice: null }
  ar: { name: Arabic,  ivr_key: "2", whisper_code: ar, twilio_say_voice: "Polly.Zeina" }
  hi: { name: Hindi,   ivr_key: "3", whisper_code: hi, twilio_say_voice: "Polly.Aditi" }
default_language: sw
```
(`twilio_say_voice` is only a fallback when a pre-recorded file is missing. Prefer `<Play>`.)

### 4.2 `config/symptoms.yaml`: the fixed parameter schema
Values: `1` = yes, `-1` = no, `0` = unknown or not mentioned.
```yaml
symptoms:
  orange_powder_under_leaf:     "Orange/yellow powder on the underside of leaves"
  yellow_spots_on_leaf:         "Yellow spots on the upper leaf surface"
  brown_spot_grey_center:       "Round brown spots with a grey/light centre"
  black_lesion_leaf_edge:       "Dark/black dead patches starting at leaf tips or edges"
  winding_brown_trails:         "Brown blotches or winding trails inside the leaf"
  leaves_falling:               "Leaves dropping early"
  dark_sunken_spots_on_berries: "Dark sunken spots on green berries"
  small_holes_in_berries:       "Small round holes in berries"
  old_leaves_pale_yellow:       "Older leaves pale/yellow all over"
  leaf_edges_burnt_brown:       "Leaf edges look burnt/brown"
  wilting_dry_weather:          "Leaves wilting/drooping in dry weather"
  rained_a_lot_recently:        "A lot of rain recently"
```

### 4.3 `config/profiles.yaml`: seed knowledge base
> ⚠️ **These are placeholder values for the demo.** The team must check them against **CABI PlantwisePlus** coffee factsheets and Kenyan coffee extension guidance, and cite the sources in the README.

Each profile lists only the symptoms that matter. Unlisted symptoms are `0` (neutral).
```yaml
profiles:
  healthy:              { orange_powder_under_leaf: -1, yellow_spots_on_leaf: -1, brown_spot_grey_center: -1,
                          black_lesion_leaf_edge: -1, winding_brown_trails: -1, leaves_falling: -1,
                          dark_sunken_spots_on_berries: -1, small_holes_in_berries: -1, old_leaves_pale_yellow: -1,
                          leaf_edges_burnt_brown: -1, wilting_dry_weather: -1 }
  leaf_rust:            { orange_powder_under_leaf: 1, yellow_spots_on_leaf: 1, leaves_falling: 1 }
  cercospora:           { brown_spot_grey_center: 1 }
  phoma:                { black_lesion_leaf_edge: 1, rained_a_lot_recently: 1 }
  leaf_miner:           { winding_brown_trails: 1 }
  coffee_berry_disease: { dark_sunken_spots_on_berries: 1, rained_a_lot_recently: 1 }
  berry_borer:          { small_holes_in_berries: 1 }
  nitrogen_deficiency:  { old_leaves_pale_yellow: 1 }
  potassium_deficiency: { leaf_edges_burnt_brown: 1 }
  drought_stress:       { wilting_dry_weather: 1, rained_a_lot_recently: -1 }
```

### 4.4 `answers/{lang}.json`
One entry per condition plus system prompts. Each entry has `text` (used for SMS and for the `<Say>` fallback) and `audio` (a file under `static/audio/{lang}/`).
```json
{
  "prompt_welcome":   {"text": "...", "audio": "welcome.mp3"},
  "prompt_consent":   {"text": "This call is recorded to help you. Press 1 to keep your voice to improve the service. Press 2 to use it only for this answer.", "audio": "consent.mp3"},
  "prompt_describe":  {"text": "After the beep, describe what you see on your coffee. Press any key when done.", "audio": "describe.mp3"},
  "prompt_wait":      {"text": "Please wait a moment.", "audio": "wait.mp3"},
  "healthy":          {"text": "Your coffee plant looks healthy.", "audio": "healthy.mp3"},
  "leaf_rust":        {"text": "Your plant likely has coffee leaf rust. Confidence: high. <vetted action>", "audio": "leaf_rust.mp3"},
  "...": {},
  "not_sure":         {"text": "We are not sure. The extension officer will call you.", "audio": "not_sure.mp3"},
  "goodbye":          {"text": "...", "audio": "goodbye.mp3"}
}
```
- Write the English master first, then the `sw`, `ar` and `hi` versions. **A native speaker must check every file before recording.**
- Add a test that **every condition in `profiles.yaml` has an entry in every language file.**
- Confidence is spoken in words (`high`), never as a percentage.

---

## 5. Data model (SQLAlchemy)

### `cases`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID (str) PK | |
| `created_at` | datetime | |
| `channel` | str | `voice` / `sms` / `demo` |
| `phone_hash` | str | SHA-256(phone + `PHONE_SALT`) |
| `phone_encrypted` | str, nullable | Fernet(phone). Used **only** for the officer callback, deleted with the case |
| `language` | str | `sw` / `ar` / `hi` (from IVR choice, or detected for SMS) |
| `detected_language` | str, nullable | What Whisper detected. Log a mismatch, don't override |
| `audio_path` | str, nullable | Storage key. `NULL` if consent = `answer_only` (after transcription) |
| `audio_consent` | str | `keep_for_training` / `answer_only` / `n/a` (SMS) |
| `transcript` | text | |
| `transcript_corrected` | text, nullable | Set by the expert |
| `asr_confidence` | float, nullable | `exp(mean(segment.avg_logprob))` |
| `parameters` | JSON | `{symptom: -1/0/1}` |
| `result` | str | condition key or `not_sure` |
| `score` | float, nullable | |
| `top2` | JSON | `[[cond, score], [cond, score]]` |
| `not_sure_reason` | str, nullable | `too_few_symptoms` / `weak_match` / `too_close` / `low_asr_confidence` / `extraction_failed` |
| `status` | str | `processing` / `answered` / `in_review` / `labeled` / `error` |
| `expert_label` | str, nullable | |
| `reviewed_by` | str, nullable | |
| `reviewed_at` | datetime, nullable | |
| `delete_after` | date | `created_at + RETENTION_DAYS` (default 365) |

### `knowledge_profiles`
`id`, `condition`, `vector` (JSON), `source` (`seed` / `verified_case`), `case_id` (nullable FK), `created_at`.
- `scripts/seed_db.py` loads `profiles.yaml` as `source=seed`.
- When an expert labels a case, insert its `parameters` as a new row with `source=verified_case`, `condition=expert_label`.

The "review queue" is simply `cases WHERE status='in_review'`.

---

## 6. Pipeline specification

### 6.1 Speech-to-text (`pipeline/stt.py`)
- Load the `faster-whisper` model **once** at startup (singleton).
- `transcribe(path, lang_hint)`: pass `language=lang_hint` (from the IVR choice, which is more reliable than detection). Also run detection once and return `detected_language`.
- `asr_confidence = exp(mean(avg_logprob))` across segments, rounded to 2 decimals.
- If `asr_confidence < ASR_MIN_CONF` (env, default `0.45`), the result is `not_sure` with reason `low_asr_confidence`.

### 6.2 Parameter extraction (`pipeline/extract.py`)
- Call Ollama `/api/chat` with `format` = a JSON schema built from `symptoms.yaml` (every key required, each an integer enum `[-1, 0, 1]`) and `options.temperature = 0`.
- System prompt (English, the same for every language):
  > You convert a coffee farmer's description into symptom flags. The description may be in Swahili, Arabic, Hindi or another language. For each symptom key, output 1 if the farmer clearly says it is present, -1 if they clearly say it is absent, 0 if not mentioned or unclear. Never guess. Output only JSON matching the schema.
  > Symptoms: {key: description for each symptom}
- Include **2 few-shot examples per language** in the prompt (store them in `config/fewshot.yaml`).
- Validate with Pydantic. Retry once on failure. If it fails again, the result is `not_sure` with reason `extraction_failed`.

### 6.3 Matching (`pipeline/match.py`)
Inputs: `params` (dict), all `knowledge_profiles` rows.

```
known = {f: v for f, v in params.items() if v != 0}
if len(known) < MIN_KNOWN (default 2): → not_sure("too_few_symptoms")

score(profile) = Σ_{f in known} pts(profile.get(f, 0), v) / len(known)
  pts(p, v) = 1.0  if p == v
              0.5  if p == 0 and v == -1      # farmer says "no" to an irrelevant symptom: neutral
              0.0  if p == 0 and v == 1       # farmer reports a symptom this condition doesn't explain
              0.0  if p == -v                 # contradiction

condition_score[c] = max(score(row) for rows with condition c)   # seed + verified cases
ranked = sort desc
if s1 < SCORE_MIN (0.75):           → not_sure("weak_match")
if s1 - s2 < MARGIN_MIN (0.15):     → not_sure("too_close")
else                                 → result = c1
```
Always return `score`, `top2` and `not_sure_reason`. All thresholds live in `.env`.

Unit tests (required):
- orange powder yes + yellow spots yes → `leaf_rust`
- everything "no" → `healthy`
- only 1 known symptom → `not_sure/too_few_symptoms`
- orange powder yes + small holes in berries yes → `not_sure/too_close` or `weak_match`
- after adding a verified case for an ambiguous vector → the same vector now returns the labeled condition

### 6.4 Answer (`pipeline/answer.py`)
- Look up `answers/{lang}.json[result]`. Return `Answer(text, audio_url)`.
- `audio_url` = `{PUBLIC_BASE_URL}/static/audio/{lang}/{file}` if the file exists, otherwise `None`. The voice route then uses `<Say>` with the language's fallback voice, and logs a warning.

### 6.5 Orchestration (`pipeline/run.py`)
`run_case(case_id)`: STT (voice only) → extract → match → answer → update the case:
- sure → `status=answered`
- not sure → `status=in_review`

**Then, if `audio_consent == answer_only`, delete the audio file and set `audio_path=NULL`.** Catch all exceptions, set `status=error` and `result=not_sure`, so the farmer always gets the "not sure" answer.

---

## 7. Twilio voice flow (`routes/voice.py`)

⚠️ **Twilio webhooks time out after about 15 s.** Whisper + LLM can take longer, so processing runs in a **background task** and the call polls with `<Redirect>`.

| Endpoint | Does | Returns (TwiML) |
|---|---|---|
| `POST /voice/incoming` | New call. Create the case (`channel=voice`, `phone_hash`, `phone_encrypted`, `status=processing`) | `<Gather numDigits=1 action=/voice/language>` playing the welcome prompt for every language ("1 Swahili, 2 Arabic, 3 Hindi") |
| `POST /voice/language?case_id=` | Save the language from the digit (unknown digit → default + repeat once) | `<Gather numDigits=1 action=/voice/consent>` + `prompt_consent` |
| `POST /voice/consent?case_id=` | Save `audio_consent` (1 = keep, 2 = answer_only) | `prompt_describe` + `<Record maxLength=30 finishOnKey="any" playBeep=true action=/voice/recorded>` |
| `POST /voice/recorded?case_id=` | Download `RecordingUrl + ".wav"` with Twilio basic auth, convert to `.ogg` via ffmpeg, save via `Storage`, **delete the recording from Twilio** (`client.recordings(sid).delete()`), start `run_case` in a background task | `prompt_wait` + `<Redirect>/voice/result?case_id=&try=1</Redirect>` |
| `POST /voice/result?case_id=&try=n` | If the case is done: play the answer, then goodbye, then `<Hangup/>`. If not done and n < 8: `<Pause length=3/>` + redirect with n+1. If n ≥ 8: play `not_sure` and set the case to `in_review` | |

- Validate `X-Twilio-Signature` on all webhooks (skip only if `TWILIO_VALIDATE=false` for local tests).
- The language prompts in `/voice/incoming` must be pre-recorded in all three languages.

## 8. SMS flow (`routes/sms.py`)
`POST /sms/incoming`: create the case (`channel=sms`, `audio_consent=n/a`, `transcript=Body`).
- **Language detection:** if the body starts with `SW`, `AR` or `HI`, use that. Otherwise detect the script with a simple heuristic: Arabic Unicode block → `ar`, Devanagari → `hi`, otherwise `sw`.
- Run the pipeline synchronously (no STT, so it's fast). Reply with TwiML `<Message>` containing `answer.text`.
- The first SMS reply also includes one short privacy line from `answers/{lang}.json["sms_privacy"]`.

## 9. Expert review page (`routes/review.py`)
HTTP basic auth (`REVIEW_USER` / `REVIEW_PASSWORD` from env).
- `GET /review`: table of `in_review` cases, newest first. Columns: date, language, `not_sure_reason`, top2, transcript preview.
- `GET /review/{id}`: shows an **audio player** (if `audio_path`; streamed via `GET /review/{id}/audio`, behind auth), the transcript, an editable transcript box, the extracted parameters, and top2 with scores. Plus a **label dropdown** (all conditions + `unclear`) and a "reviewed by" field.
- `POST /review/{id}`: save `expert_label`, `transcript_corrected`, `reviewed_by`, `reviewed_at`, `status=labeled`. If the label ≠ `unclear`, insert a `knowledge_profiles` row (`source=verified_case`).
- Optional callback (stretch): a "Send answer to farmer" button sends the labeled answer by SMS, using the decrypted phone number.
- Keep the UI plain: one CSS block, no JS framework.

## 10. Demo route without Twilio (`routes/demo.py`)
**Build this before the Twilio flow.** It is the safety net for the video.
- `GET /demo`: a page to pick a language, pick consent, and either upload an audio file, **record from the browser microphone** (MediaRecorder API), or type text.
- `POST /demo`: create the case (`channel=demo`), run the pipeline synchronously, and show the transcript, parameters, top2, result, answer text and an audio player for the answer.
- `scripts/demo_cli.py --lang sw --audio sample.wav` or `--text "..."` prints the same information.

## 11. Privacy and retention
- `privacy.py`: `hash_phone(phone)` = SHA-256 with `PHONE_SALT`. `encrypt_phone` / `decrypt_phone` use `FERNET_KEY`.
- **Never log plain phone numbers or transcripts at INFO level.**
- `scripts/cleanup.py`: delete cases and their audio where `delete_after < today`. Also delete audio where `audio_consent=answer_only` and `audio_path` is not null (a safety net).
- Delete-my-data (stretch): an IVR option `9` deletes all cases for that `phone_hash`.

## 12. Evaluation scripts (results go into README and the video)
- `scripts/eval_asr.py`: take 25 FLEURS test clips each for `sw_ke`, `ar_eg`, `hi_in`, transcribe them with the configured Whisper model, and print the **WER per language** with `jiwer`. Save the results to `eval/asr_results.csv`.
- `scripts/eval_extract.py`: `eval/extract_testset.yaml` holds about 10 sentences per language with expected symptom flags, written by the team and **labeled as synthetic**. Report per-language exact-match and per-symptom accuracy.
- `scripts/eval_end2end.py`: run text cases through extract → match and report the correct, wrong and not_sure rates. **A low "wrong" rate matters more than a high "correct" rate.**

## 13. Environment (`.env.example`)
```
DATABASE_URL=sqlite:///./data/shamba.db
STORAGE_BACKEND=local            # local | minio
AUDIO_DIR=./data/audio
MINIO_ENDPOINT= MINIO_ACCESS_KEY= MINIO_SECRET_KEY= MINIO_BUCKET=voices
WHISPER_MODEL=small
WHISPER_DEVICE=cpu
OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=gemma3:4b
TWILIO_ACCOUNT_SID= TWILIO_AUTH_TOKEN= TWILIO_VALIDATE=true
PUBLIC_BASE_URL=https://<ngrok-id>.ngrok.app
PHONE_SALT=change-me
FERNET_KEY=                       # python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
REVIEW_USER=expert  REVIEW_PASSWORD=change-me
ASR_MIN_CONF=0.45  MIN_KNOWN=2  SCORE_MIN=0.75  MARGIN_MIN=0.15
RETENTION_DAYS=365
```

---

## 14. Milestones (build in this order)

| # | Milestone | Done when | Time box |
|---|---|---|---|
| M0 | Skeleton: repo layout, config loading, DB models, `init_db`, `seed_db.py`, `/health` | `pytest` passes, DB seeded with 10 profiles | 30 min |
| M1 | **Core pipeline, text path:** `extract.py`, `match.py`, `answer.py`, `run.py`, `demo_cli.py --text` | A Swahili sentence about orange powder returns `leaf_rust` with the Swahili answer text. All match unit tests pass | 2 h |
| M2 | **Voice path:** `stt.py`, storage, ffmpeg conversion, `demo_cli.py --audio` | A recorded Swahili clip goes end to end. Audio is deleted for `answer_only` | 1 h |
| M3 | **Demo web page** (`/demo` with mic recording) | Full flow works in the browser **with Wi-Fi off** (Ollama + Whisper local) | 1 h |
| M4 | Review page + feedback loop | A not-sure case is labeled in the UI, and the same input now returns a sure answer | 1.5 h |
| M5 | Twilio voice flow + ngrok | A real phone call to the Twilio number hears the answer in the chosen language | 2 h |
| M6 | SMS flow | An SMS in Arabic gets an Arabic reply | 45 min |
| M7 | Privacy: hashing, encryption, cleanup script, signature validation | Tests for hash, encryption and cleanup pass | 45 min |
| M8 | Eval scripts + README (setup, data sources, **limits / what the data does not cover**, licenses) | `eval/*.csv` produced and numbers pasted into the README | 1 h |
| Stretch | MinIO backend, officer callback SMS, IVR delete-my-data, MMS for a fourth language (e.g. Kikuyu), logistic regression classifier as a second opinion | | |

**If time runs out:** M0–M4 + M8 already make a complete, honest demo (browser mic standing in for the phone). M5 is the wow factor, so try it, but don't let it block the rest.

---

## 15. README must include (judges score this)
- One-line problem statement: *"Because of Shamba Call, a smallholder coffee farmer will know within minutes whether her coffee is sick and what to do, which she would otherwise learn months late or never; we know because [evidence: FAOSTAT yield trend, extension-officer coverage, GSMA basic-phone ownership]."*
- Why AI and not a plain SMS menu: free speech in local languages becomes structured symptoms, which a keypad or spreadsheet can't do.
- Guardrails: fixed answers, not-sure fallback, human review, and verified-only learning.
- Data sources with licenses: FLEURS, Common Voice, seed profiles (CABI / extension guides), and the synthetic test sets (labeled as synthetic).
- **What the data does not cover:**
  - The seed profiles are not agronomist-validated.
  - No real farmer recordings yet.
  - Whisper is weaker in Swahili and does not support Kikuyu.
  - Arabic dialects differ from standard Arabic.
  - Nutrient deficiency and drought look alike.
- Model licenses: Whisper MIT, Gemma terms, MMS CC-BY-NC (if used).
- How to add a language (config + answers + audio + test sentences, no code).

## 16. Out of scope for the hackathon
Image diagnosis, price information, real farmer registry integration, production deployment, and multi-tenant auth.
