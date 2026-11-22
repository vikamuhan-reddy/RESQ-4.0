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
| Incident intake and live dashboard (SSE) | Extraction uses keyword rules unless `GEMINI_API_KEY` is set; the Gemini path is being upgraded |
| Per-field source and verification status | Dispatch is **simulated**: no agency is contacted |
| Separate caller and incident locations | Landmark pins use fixed approximate coordinates (being replaced) |
| Operator corrections with revision history | No login or roles yet |
| Dropped call keeps the incident open | No measured accuracy yet; an evaluation set is planned |
| SQLite persistence and duplicate-proof dispatch requests | |

The step-by-step roadmap is in [PLAN.md](PLAN.md).

## Run it

```powershell
pip install -r requirements.txt
copy .env.example .env      # optional: add GEMINI_API_KEY
python run_server.py        # http://127.0.0.1:8000  (API docs at /docs)
python tests/test_resq.py   # uses a throwaway DB
```

## Layout

```
backend/
  main.py                 FastAPI routes + SSE stream
  core/orchestrator.py    incident state and operator actions
  core/persistence.py     SQLite store (RESQ_DB_PATH overrides the file)
  core/idempotency.py     one action per idempotency key
  agents/voice_agent.py   transcript -> structured fields
  agents/reasoning_agent.py   completeness, contradictions, related incidents
  agents/coordination_agent.py  department proposals
  services/               Gemini extraction, geocoding
static/                   operator dashboard (HTML + vanilla JS + Leaflet)
tests/test_resq.py        end-to-end smoke test
```

## Safety

RESQ is decision support, not an autonomous dispatcher. It never contacts a real agency in this prototype, and a human approves every action.
