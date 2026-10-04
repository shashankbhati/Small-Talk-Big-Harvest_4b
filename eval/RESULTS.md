# Shamba Call: End-to-End Test Results

Generated 2026-10-04 05:37 by `scripts/report.py`. Machine: Windows 11, NVIDIA RTX 3050 Ti Laptop (4 GB), 14 GB RAM.

## Summary

| Check | Result |
|---|---|
| Unit tests (`pytest`) | 87 passed, 1 warning |
| Live scenarios (real models) | 13/13 passed |
| Speech end to end: wrong diagnoses | 1 of 72 cases |
| Text end to end: wrong diagnoses | 0 of 72 cases |

**Model stacks tested**

| Stack | Speech-to-text | Symptom extraction |
|---|---|---|
| Hosted (default) | Together `openai/whisper-large-v3` | Together `Qwen/Qwen3.5-9B` |
| Local (fallback) | faster-whisper `large-v3-turbo` on GPU | Ollama `gemma3:4b` + keyword check |

Decision thresholds: `MIN_KNOWN=2`, `SCORE_MIN=0.75`, `MARGIN_MIN=0.15`, `ASR_MIN_CONF=0.45`, `LEXICON_CHECK=always`.

## 1. Unit tests

`pytest`: **87 passed, 1 warning in 2.46s**. Covers config, database, matching rules, answers in every language, extraction validation and retries, storage and audio deletion, demo/review/voice/SMS routes, Twilio signature check, privacy (hashing, encryption, retention, logs), retry + local fallback, keyword check.

## 2. Live scenarios (run 2026-10-04 05:13)

The app runs in-process against the real models (`python scripts/e2e_scenarios.py`).

| # | Scenario | Result | Time | Details |
|---|---|---|---|---|
| 1 | Health check: all model backends reachable | ✅ PASS | 1.5 s | Together, Ollama (gemma3:4b) and local Whisper all available |
| 2 | Demo text (sw): leaf rust description → leaf rust answer in sw | ✅ PASS | 2.7 s | leaf_rust, score 1.0, LLM=together |
| 3 | Demo text (ar): leaf rust description → leaf rust answer in ar | ✅ PASS | 2.6 s | leaf_rust, score 1.0, LLM=together |
| 4 | Demo text (hi): leaf rust description → leaf rust answer in hi | ✅ PASS | 3.5 s | leaf_rust, score 1.0, LLM=together |
| 5 | Demo voice (sw, consent=answer_only): audio → leaf rust, audio deleted | ✅ PASS | 4.1 s | leaf_rust, ASR conf 0.95, STT=together, LLM=together, audio deleted |
| 6 | Demo voice (ar, consent=keep): audio → leaf rust, audio kept | ✅ PASS | 3.4 s | leaf_rust, ASR conf 0.96, audio stored |
| 7 | SMS (Arabic): Arabic reply, privacy line only on first contact | ✅ PASS | 5.5 s | Arabic leaf-rust reply; privacy notice on first SMS only |
| 8 | Phone (IVR): call → Arabic → consent → recording → answer played | ✅ PASS | 3.4 s | leaf_rust played in Arabic, consent=answer_only → audio deleted |
| 9 | Feedback loop: not-sure case labeled by expert → same input now answered | ✅ PASS | 6.3 s | not_sure (weak_match) → labeled berry_borer → answered berry_borer; 1 verified case in KB |
| 10 | Review page requires login | ✅ PASS | 0.0 s | 401 without / with wrong credentials |
| 11 | Privacy: phone number never stored in plain text; key 9 deletes caller data | ✅ PASS | 0.0 s | 3 cases with hashed/encrypted numbers; all deleted via key 9 |
| 12 | Together outage → local fallback (text) | ✅ PASS | 27.5 s | leaf_rust via STT=None, LLM=ollama |
| 13 | Together outage → local fallback (voice) | ✅ PASS | 39.5 s | leaf_rust via STT=local, LLM=ollama |

## 3. Speech end to end

Speech end to end: synthetic audio of the 36 test sentences → speech-to-text → extraction → diagnosis. Low `wrong` matters more than high `correct`. The audio is clean synthetic speech (edge-tts), easier than a real phone line.

| stack | lang | n | correct | wrong | not_sure | mean_asr_conf | sec_per_case |
|---|---|---|---|---|---|---|---|
| openai/whisper-large-v3 + Qwen/Qwen3.5-9B | sw | 12 | 92% | 0% | 8% | 0.9 | 3.8 |
| openai/whisper-large-v3 + Qwen/Qwen3.5-9B | ar | 12 | 100% | 0% | 0% | 0.98 | 5.7 |
| openai/whisper-large-v3 + Qwen/Qwen3.5-9B | hi | 12 | 83% | 0% | 17% | 0.97 | 8.8 |
| large-v3-turbo (local) + gemma3:4b (local) | sw | 12 | 92% | 0% | 8% | 0.87 | 23.0 |
| large-v3-turbo (local) + gemma3:4b (local) | ar | 12 | 83% | 0% | 17% | 0.94 | 23.0 |
| large-v3-turbo (local) + gemma3:4b (local) | hi | 12 | 92% | 8% | 0% | 0.94 | 23.2 |

## 4. Text end to end

Text end to end: test sentence → extraction → diagnosis (also what SMS does).

| provider | model | lang | n | correct | wrong | not_sure |
|---|---|---|---|---|---|---|
| ollama | gemma3:4b | sw | 12 | 100% | 0% | 0% |
| ollama | gemma3:4b | ar | 12 | 83% | 0% | 17% |
| ollama | gemma3:4b | hi | 12 | 83% | 0% | 17% |
| together | Qwen/Qwen3.5-9B | sw | 12 | 92% | 0% | 8% |
| together | Qwen/Qwen3.5-9B | ar | 12 | 100% | 0% | 0% |
| together | Qwen/Qwen3.5-9B | hi | 12 | 100% | 0% | 0% |

## 5. Symptom extraction

Symptom extraction: how many of the 24 symptom flags the LLM got right. `exact_match` = all 24 flags right for a sentence; many misses are harmless (e.g. reading "the plant is healthy" as "no" to every symptom).

| provider | model | lang | n | exact_match | symptom_accuracy | failed | sec_per_case |
|---|---|---|---|---|---|---|---|
| ollama | gemma3:4b | sw | 12 | 92% | 100% | 0 | 22.23 |
| ollama | gemma3:4b | ar | 12 | 58% | 97% | 0 | 22.29 |
| ollama | gemma3:4b | hi | 12 | 58% | 96% | 0 | 22.41 |
| together | Qwen/Qwen3.5-9B | sw | 12 | 75% | 93% | 0 | 2.91 |
| together | Qwen/Qwen3.5-9B | ar | 12 | 92% | 99% | 0 | 2.85 |
| together | Qwen/Qwen3.5-9B | hi | 12 | 92% | 94% | 0 | 3.26 |

## 6. Speech recognition (FLEURS)

Speech recognition on FLEURS (25 real read-speech clips per language): word error rate (lower is better).

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

## 7. Wrong diagnoses

| test | stack | lang | expected | got | transcript |
|---|---|---|---|---|---|
| speech | large-v3-turbo (local) + gemma3:4b (local) | hi | not_sure | root_rot | पेड मुर्जा रहा है और पत्या पीली हो रही है। |

## 8. Findings

- **The local stack made one wrong diagnosis (Hindi speech).** Local Whisper misspelled "मुरझा" (wilting) as "मुर्जा"; gemma3:4b then invented *poor growth* and the matcher answered *root rot* instead of "not sure". Swahili has a keyword list that blocks unconfirmed "yes" answers from the local model; **Hindi and Arabic don't have one yet**. Recommended next step: add `config/lexicon/hi.yaml` and `config/lexicon/ar.yaml`.
- **The feedback loop fixes ambiguous matches, not missed symptoms.** When the LLM misses a symptom and only one symptom is left, the case stops at `too_few_symptoms` before the knowledge base is consulted, so an expert label can't change the next answer. Found when Qwen3.5-9B missed *"buni zina vitundu vidogo"* (berries have small holes).
- **The Swahili keyword check now runs for both models** (`LEXICON_CHECK=always`). On the current test set it cost Qwen3.5-9B nothing and recovered *matundu* (holes), which Qwen missed after *unga wa machungwa*.
- **Together AI had real timeouts** during one eval run (before this report). Retry + local fallback is what keeps the farmer answered; with fallback disabled, those cases became "not sure".
- **Local Whisper large-v3-turbo on the laptop GPU matches Together's Whisper large-v3** on FLEURS (Swahili WER 0.35 vs 0.33; Hindi 0.15 vs 0.24) at ~1.2 s per clip.
- **Speed:** Together answers a voice case in ~4–9 s; the fully local stack takes ~23 s per case; a Together outage (retry + local) takes ~30–40 s. The phone call waits up to ~75 s.

## 9. Test data and caveats

- Test set: `eval/extract_testset.yaml`, 12 **synthetic** sentences per language (8 conditions, healthy, 3 cases that should get "not sure"), written by the team from the knowledge base. Some were written after the Swahili keyword list, so real-world accuracy will be lower.
- Speech tests use clean synthetic audio and FLEURS read speech, not real farmers on a phone line.
- Knowledge base: `knowledge/coffee_disease_knowledge_base.xlsx` (team-provided, no citations yet).

## 10. How to reproduce

```bash
pytest -q | tail -1 > eval/pytest_summary.txt
python scripts/e2e_scenarios.py                                         # live scenarios
python scripts/e2e_speech.py                                            # speech e2e, hosted stack
STT_PROVIDER=local LLM_PROVIDER=ollama python scripts/e2e_speech.py --lang sw   # local stack, per language
LLM_FALLBACK= python scripts/eval_extract.py                             # text e2e + extraction, hosted
LLM_PROVIDER=ollama LLM_FALLBACK= python scripts/eval_extract.py --lang sw      # local, per language
python scripts/eval_asr.py; STT_PROVIDER=local STT_FALLBACK= python scripts/eval_asr.py
python scripts/report.py                                                # rebuild this file
```
