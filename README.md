# Coffee Voice Advisor (Hack-Nation x World Bank, Agriculture)

A farmer calls from any phone and describes what she sees on her coffee plants.
Speech recognition turns her voice into text. A small local LLM fills a FIXED symptom form.
A small probabilistic classifier combines those symptoms with recent weather at her farm and
CONFIRMED cases from nearby farmers. She hears pre-approved advice, or "not sure, the officer will call you".

```
phone call -> Twilio -> /recorded -> Whisper (speech-to-text)
          -> Ollama small LLM (symptom form, JSON schema only)
          -> classifier (+ NASA POWER weather + nearby confirmed cases + knowledge base)
          -> confident: advice clip | unsure: "officer will call" -> case saved -> /dashboard
```

## Folder layout
| Path | What it is |
|---|---|
| `app/main.py` | FastAPI server: Twilio call flow, test API, officer dashboard |
| `app/asr.py` | Speech-to-text (faster-whisper, CPU) |
| `app/extractor.py` | LLM symptom extraction (Ollama, forced JSON schema) + keyword fallback |
| `app/classifier.py` | Naive-Bayes-style classifier + confidence/"unsure" rule |
| `app/weather.py` | NASA POWER rainfall/temperature, cached for offline use |
| `app/db.py` | SQLite: farmer registry (hashed phone), consent, cases |
| `app/prompts.py` | Fixed phrases the call can say |
| `data/knowledge_base.json` | Symptoms, problems, starting priors, advice texts (DRAFT - get an agronomist to check) |
| `static/audio/` | Recorded voice clips (`<key>.mp3`) |
| `scripts/test_pipeline.py` | Run the pipeline on example sentences, no phone needed |
| `scripts/seed_synthetic.py` | Add SYNTHETIC confirmed cases nearby for the demo |

## 1. Install (Windows, PowerShell, inside this folder)
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env      # then edit .env
```
If PowerShell blocks activation: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## 2. Small local LLM (Ollama)
1. Install from https://ollama.com (Windows installer).
2. `ollama pull qwen2.5:1.5b`  (about 1 GB). Ollama then runs in the background on port 11434.
3. Without Ollama the system still works using simple English keyword rules (`keyword-fallback`).

## 3. Test without a phone
```powershell
python -m scripts.seed_synthetic --rust 6 --miner 1     # synthetic nearby cases, marked synthetic
python -m scripts.test_pipeline
python -m scripts.test_pipeline "orange powder under the leaves and they are falling"
```
Check that `METHOD` shows `llm:qwen2.5:1.5b`, not `keyword-fallback`.

## 4. Run the server
```powershell
uvicorn app.main:app --port 8000
```
- http://localhost:8000/dashboard  (extension officer view)
- Text test: `curl -X POST localhost:8000/api/text -H "Content-Type: application/json" -d "{\"text\":\"orange powder under leaves\"}"`
- Audio test: `curl -F "file=@sample.wav" localhost:8000/api/audio`

The first start downloads the Whisper `small` model (about 500 MB) once.

## 5. Real phone call (Twilio + ngrok)
1. Install ngrok (https://ngrok.com), log in, run: `ngrok http 8000`. Copy the https URL.
2. Put it in `.env` as `BASE_URL=https://....ngrok-free.app` and restart uvicorn.
3. Twilio console: create a trial account, buy a phone number with Voice (a US number is instant).
4. Phone Numbers -> your number -> Voice Configuration -> "A call comes in": Webhook, `https://....ngrok-free.app/voice`, HTTP POST. Save.
5. Trial accounts: verify your own mobile under Verified Caller IDs, otherwise your call is rejected.
6. Put `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN` in `.env` (needed to download and then delete the recording).
7. Call the number. Flow: consent (press 1) -> data-sharing question (1/2) -> describe after the beep -> press # -> wait -> advice.

Watch the uvicorn console: each call prints the transcript, features, weather, ranking and decision.

Notes:
- A trial account plays a short "trial account" message first. Upgrading removes it.
- Phone audio is 8 kHz, so transcription is worse than on a laptop mic. Measure it, it is useful evidence.
- The recording is downloaded, transcribed, deleted locally AND deleted from Twilio (`DELETE_RECORDINGS=true`).
- In this mode the server needs internet (Twilio). For the offline proof, run `scripts/test_pipeline.py` or `/api/audio` with Wi-Fi off: Whisper, Ollama, the classifier and cached weather all run locally.

## 6. Recorded voice clips (local language)
Record one mp3 per key and put it in `static/audio/`. Missing clips fall back to Twilio reading the English text.
- Prompts (`app/prompts.py`): `welcome_consent`, `consent_improve`, `describe`, `please_wait`, `goodbye`, `no_consent`, `deleted`, `error`
- Advice (`data/knowledge_base.json` -> `advice`): `leaf_rust`, `brown_eye_spot`, `leaf_miner`, `coffee_berry_disease`, `berry_borer`, `drought_stress`, `nutrient_deficiency`, `unsure`, `no_input`

## 7. How the decision works
- Probability for each problem = starting prior x weather factor x nearby-confirmed-cases factor x product of P(symptom | problem).
- "Confident" only if at least 2 symptoms were described, the top problem is >= 0.60, and it leads the second by >= 0.20 (see `.env`). Otherwise the farmer hears "not sure" and the case goes to the officer.
- Only CONFIRMED cases (officer or photo check) count as nearby reports, so wrong guesses do not reinforce themselves.
- The LLM never writes what the farmer hears. It only fills the symptom form.

## Honest limits (put these in the submission)
- Knowledge-base numbers are hand-set starting values, not measured. They need agronomist review and real confirmed cases.
- Nearby-farmer data in the demo is synthetic (`synthetic=1`).
- The keyword fallback is English only. Local-language quality depends on Whisper/MMS support for that language: test it on real speakers.
- Advice texts are drafts and must be checked by an agronomist before real use.
