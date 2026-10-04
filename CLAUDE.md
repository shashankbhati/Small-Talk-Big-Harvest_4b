# Project context (handoff from Claude Cowork session, 2026-10-04)

## Hackathon
- Hack-Nation x World Bank "Small AI for Development" Hackathon, Challenge 04. Competition weekend Oct 3-4, 2026.
- Sector chosen: **Agriculture**. Persona "Noor": 38, coffee smallholder (2 ha, coffee upper slope, maize/beans lower), cooperative member.
  - Phones: her own (calls, SMS, mobile money; brief does NOT say it is a basic phone, but treat it as one) + daughter's smartphone she only uses on weekends when daughter helps. No Wi-Fi, buys 3G bundles. Phone stays at house while she is on the slope.
  - Problem: coffee yields falling, doesn't know why; extension officer visits ~twice a year; at harvest buyer names price with no reference (price = out of scope v1).
- Rules: runs on a device user already has; core feature works offline; model files small enough to side-load / send over weak link; at least one interaction in a named local language (voice or text); human-in-the-loop; avoid hallucinations; must cite data and state what data does NOT cover.
- Judging: built solution 25%, relevance 20%, data grounding 15%, evidence it works 15%, clarity/value of AI 15%, scalability 10%, responsible AI pass/fail.
- Deliverables: working prototype (code/link) + 2-5 min video (problem statement in template "Because of this tool, [user] will [action] by [when] that they would otherwise [not do/do late/do worse]; we know because [evidence]", AI capabilities + why not SMS/spreadsheet, demo, where it sits in user's day, "what localizing AI means to you").

## Decided solution: Coffee Voice Advisor
Noor calls a number from any phone -> describes symptoms in her language -> Whisper speech-to-text -> small local LLM (Ollama, qwen2.5:1.5b) fills a FIXED symptom JSON schema (never writes advice) -> naive-Bayes-style classifier combines symptoms + recent weather (NASA POWER, cached) + CONFIRMED nearby cases + knowledge base -> confident: pre-approved advice clip; unsure: "officer will call you" -> case saved -> extension officer dashboard.
- Optional later: weekly leaf photos on daughter's smartphone -> small offline CV model (MobileNetV3/EfficientNet-Lite on BRACOL, test on RoCoLe/field photos) confirms/corrects call-based guesses -> labels feed classifier.
- Key design choices (keep these):
  - LLM only extracts features; all spoken output is pre-recorded/approved (hallucination guardrail).
  - Only confirmed cases (officer/photo) count as nearby reports (avoids feedback loop).
  - Unsure rule: >=2 symptoms, top prob >=0.60, margin >=0.20, else refer to officer.
  - Privacy: consent on call (press 1), separate opt-in for using data to improve (1/2), press 9 deletes data; no voice stored (deleted locally and on Twilio); phone numbers salted-hashed; location at village level.
  - "Offline" framing: Noor needs no data (normal voice call). Backend uses only small open models and can run on a local box at the cooperative with internet off. User asked organisers whether server-side small models satisfy the offline rule (answer pending).
- Demo default location: Kodagu, Karnataka, India (coffee region). Local language NOT decided yet (depends on native speakers available for recordings/test set). Calls currently in English.

## Code status (this folder)
- FastAPI app in `app/` (see README.md for full layout and setup). Twilio voice flow: /voice -> /consent -> /consent-improve -> /describe -> /recorded (background thread: download, transcribe, pipeline) -> /result (polls). Test API /api/text, /api/audio; dashboard /dashboard with officer confirm.
- Tested in a Linux VM with keyword fallback (no Whisper/Ollama there): pipeline, TwiML endpoints, dashboard all OK. NOT yet run on the user's Windows machine with Whisper, Ollama or real Twilio.
- `data/knowledge_base.json`: likelihood numbers and advice texts are hand-set DRAFTS (need agronomist review; say so in submission).
- `scripts/seed_synthetic.py` adds synthetic confirmed nearby cases (synthetic=1).

## Next steps
1. Run on Windows: venv, requirements, .env, Ollama pull, test_pipeline (check METHOD = llm), uvicorn, ngrok, Twilio webhook, real call.
2. Choose local language; record clips into static/audio/<key>.mp3; collect 30-50 native-speaker descriptions as a test set; measure WER and feature-extraction accuracy (also on 8 kHz phone audio).
3. Evidence charts: extraction accuracy, classifier accuracy vs number of confirmed cases (synthetic, labelled), offline demo with Wi-Fi off.
4. Possibly: follow-up question when a key symptom is unknown; CV photo model; USSD/SMS channel.
5. Video + submission write-up (honest limits section in README).

## About the user
- Shashank, data scientist (image analysis: CNN/U-Net/GAN), no prior audio-ML experience. Windows machine, project folder C:\Users\shash\OneDrive\Desktop\4B.
- Prefers honest, direct assessments; wants to stand out vs other teams using Claude with similar ideas.
