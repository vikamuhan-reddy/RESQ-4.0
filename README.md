# RESQ 4.0 — AI co-pilot for emergency call-takers

> 112 gives people one number. RESQ makes sure what they say on that call reaches the right department correctly, in seconds, even if the caller panics, speaks Tamil, or gets cut off.

## The problem

The person answering an emergency call has to understand a panicking caller, often in Tamil or Tamil-English mix and over street noise, get the location right, type it in, and forward it to the right department. Details get lost at exactly that step: the wrong landmark, the caller's location confused with the incident's, a call that drops before the address is given.

## What RESQ does

1. **Listens:** browser microphone or typed text, in Tamil and English.
2. **Understands:** turns the call into a structured incident (type, injuries, hazards, caller location vs incident location). Every field records where it came from and whether anyone has verified it.
3. **Asks back:** flags missing information and suggests the next question in the caller's language.
4. **Routes:** proposes the right department(s). A human operator approves every dispatch.
5. **Keeps going:** if the call drops, the incident stays open with whatever was captured.

## Status

| Working | Not yet |
|---|---|
| Gemini understands Tamil, English and mixed calls, re-reading the whole conversation each turn | Operators can't yet confirm a location on the map, so no incident is pinned |
| Real AI failures (timeout, overload, bad key, no network) are logged, flagged for review, and fall back to keyword rules | No login or roles |
| Rules decide the departments; a human approves every dispatch | Telegram stands in for real department systems; **no real agency is contacted** |
| A dispatch counts as sent only when Telegram confirms delivery; failures are shown and can be retried | Audio transcription through Gemini is built but not yet tested with live microphone recordings (browser speech recognition is used today) |
| The next question is spoken in the caller's language (needs a browser with a Tamil voice, e.g. Microsoft Edge) | Accuracy is measured on 30 team-written calls, not real call audio |
| Locations stay in the caller's words; nothing is pinned until confirmed | |
| Enforced incident state machine, per-field provenance, operator corrections with history, SQLite persistence | |

The step-by-step roadmap is in [PLAN.md](PLAN.md).

## Evaluation

Measured on [tests/eval_calls.jsonl](tests/eval_calls.jsonl): 30 calls **we wrote** (10 Tamil, 10 English, 10 Tamil-English), including dropped calls, callers not at the scene, and non-emergencies. Labels follow what the caller actually said. One run, 2026-11-23.

| Metric | Keyword rules (fallback) | RESQ with Gemini |
|---|---|---|
| Category | 18/30 (60%) | 30/30 (100%) |
| Right departments routed | 16/30 (53%) | 30/30 (100%) |
| Injuries reported or not | 16/25 (64%) | 25/25 (100%) |
| Caller away from the scene detected | 2/4 | 4/4 |
| Incident location captured | 6/30 (20%) | 29/30 (97%) |
| Median time per call | <0.1 s | 2.2 s (slowest 7.1 s) |

Thirty synthetic calls is a small test. These numbers show the pipeline works end to end; they don't show it is 100% accurate on real calls. The two misses: a wrong-number caller marked "not at the scene", and a cut-off call where "near the" was taken as the location.

Reproduce with `python tests/eval.py` (Gemini) or `python tests/eval.py --keywords` (baseline).

## Run it

```powershell
pip install -r requirements.txt
copy .env.example .env      # optional: add GEMINI_API_KEY
python run_server.py        # http://127.0.0.1:8000  (API docs at /docs)
python tests/test_resq.py   # offline checks, throwaway DB
python tests/eval.py        # 30-call accuracy run (uses your Gemini key)
```

For the Telegram dispatch demo, fill in `TELEGRAM_BOT_TOKEN` and the `TELEGRAM_CHAT_*` IDs in `.env` (see `.env.example`). Without them, approvals are marked as a simulated delivery.

## Layout

```
backend/
  main.py                 FastAPI routes + SSE stream
  core/orchestrator.py    incident state and operator actions
  core/persistence.py     SQLite store (RESQ_DB_PATH overrides the file)
  core/idempotency.py     one action per idempotency key
  agents/voice_agent.py   transcript -> structured fields
  agents/reasoning_agent.py   completeness, contradictions, related incidents
  agents/coordination_agent.py  routing rules + department proposals
  services/gemini_service.py    typed Gemini extraction + audio transcription
  services/dispatch_service.py  dispatch message template + Telegram delivery
static/                   operator dashboard (HTML + vanilla JS + Leaflet)
tests/test_resq.py        offline end-to-end checks
tests/eval.py             accuracy evaluation on tests/eval_calls.jsonl
```

## Safety

RESQ is decision support, not an autonomous dispatcher. It never contacts a real agency in this prototype, and a human approves every action.
