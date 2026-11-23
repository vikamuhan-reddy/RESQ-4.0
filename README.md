# RESQ 4.0 — AI co-pilot for emergency call-takers

> 112 gives people one number. RESQ makes sure what they say on that call reaches the right department correctly, in seconds, even if the caller panics, speaks Tamil, or gets cut off.

## The problem

The person answering an emergency call has to understand a panicking caller, often in Tamil or Tamil-English mix and over street noise, get the location right, type it in, and forward it to the right department. Details get lost at exactly that step: the wrong landmark, the caller's location confused with the incident's, a call that drops before the address is given.

## How it works

```
Caller speaks (Tamil / English / mixed)
        │
        ▼
Gemini reads the whole conversation ──► next question, spoken back in the caller's language
        │
        ▼
Rules pick the departments ──► automatic PRE-ALERT to each department (Telegram)
        │
        ▼
Operator confirms the place on the map, then confirms the dispatch
        │
        ▼
CONFIRMED DISPATCH + map link ──► department taps "Acknowledge" ──► dashboard and caller screen update live
```

1. **Listen.** The caller talks on the caller screen (`/caller`), or the call-taker types or speaks into the dashboard. The recording is sent to Gemini for transcription, with the browser's own speech recognition as a fallback.
2. **Understand.** Gemini reads the whole conversation so far and returns a fixed, typed record: what happened, injuries, hazards, where the incident is, whether the caller is actually there, and what is still missing.
3. **Ask back.** RESQ asks the single most useful next question, in Tamil or English, and speaks it aloud. It knows which questions it has already asked, so each one builds on the last answer.
4. **Route.** Fixed rules, not AI, choose the departments: an accident goes to Traffic Police, plus an ambulance if anyone is hurt; a fire goes to Fire & Rescue; and so on. Each department gets an automatic **pre-alert** so it can get ready.
5. **Locate.** The spoken place is looked up on the map and shown as an amber **suggested** pin. One operator click confirms it.
6. **Dispatch.** The operator confirms the dispatch. The department receives a **confirmed dispatch** with the map link and an **Acknowledge** button. One tap marks it acknowledged everywhere.
7. **Keep going.** If the call drops, the incident stays open with everything captured. If Gemini fails, the incident is flagged for review and keyword rules take over. If a second person reports the same emergency, the operator merges the two reports, so it isn't dispatched twice.

## Features

**Understanding the call**
- Gemini structured output on the whole, speaker-labelled conversation; Tamil, English and Tamil-English.
- Caller location kept separate from incident location ("I'm on the bus, the accident is at Gemini flyover").
- Every field records its source (caller, AI, operator) and whether anyone has verified it. Operator corrections are kept with history and are never overwritten by the AI.

**Location**
- The spoken place is looked up automatically (OpenStreetMap, limited to the city) and shown as an amber **suggested** pin.
- If the caller adds detail, the pin moves. If they correct the place to one the map can't find, the pin is removed rather than left somewhere wrong.
- The operator confirms with one click (or uses "Find on map", or clicks the right spot), and the pin turns red. Only then is the location marked verified.
- The caller's phone can share its own location from the caller screen.

**Dispatch**
- Routing table in code, with a test covering every category.
- An automatic pre-alert goes to each routed department; the operator confirms the actual dispatch.
- A dispatch counts as **sent only when Telegram confirms delivery**. Failures are shown with the reason and a Retry button.
- Departments acknowledge with one tap in Telegram.
- A second report of the same place within 15 minutes is flagged. Merging it cancels its pending dispatches and tells the pre-alerted department.

**Resilience**
- Real AI failures (timeout, overload, bad key, no network) are logged, flagged for operator review, and fall back to keyword rules.
- A dropped call keeps the incident open; departments are already proposed by then.
- Every state change goes through one validated state machine and is written to an audit timeline.

**Operator dashboard**
- Live queue and incident view (updates over Server-Sent Events).
- Call conversation as a chat, map, fields with source and verification, reasoning (what's missing, contradictions, possible duplicates), dispatch cards, audit timeline.
- A timer from call start to the first department notified.

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

This run was made before Gemini started receiving the speaker-labelled conversation. A re-run later that day hit a Gemini overload (both models answered "503 high demand"): Gemini answered only 4 of 30 calls, and the rest fell back to keyword rules. That run measured Google's availability, not accuracy, so it isn't in the table. It does show the fallback working: every call still produced an incident.

Reproduce with `python tests/eval.py` (Gemini) or `python tests/eval.py --keywords` (baseline).

## Known limitations

- **No real agency is contacted.** Telegram stands in for each department's dispatch system, and every message is marked SIMULATION.
- **No login or roles.** The operator name is just a label.
- **Accuracy is measured on 30 calls we wrote**, not on real call recordings.
- **Map search covers Chennai** by default (set `GEOCODE_VIEWBOX` for another city).
- **The caller screen needs https or localhost** for the microphone and location. That's fine on the demo laptop, but not on a phone over plain Wi-Fi.
- **Spoken questions need a browser with a Tamil voice.** Microsoft Edge has one; many Chrome installs don't.
- **Gemini's free tier sometimes answers "overloaded".** RESQ tries a second model, then falls back to keyword rules.
- **There is no button to close or resolve an incident yet.**

## Setup

**You need:** Python 3.10+ (tested on 3.12), a free [Gemini API key](https://aistudio.google.com), and Microsoft Edge for the Tamil voice. Telegram is optional.

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Then fill in `.env`. It is git-ignored, so keys never get committed:

| Variable | What it is |
|---|---|
| `GEMINI_API_KEY` | Required for AI understanding. Without it, RESQ runs on keyword rules only. |
| `TELEGRAM_BOT_TOKEN` | Optional. Without it, pre-alerts and dispatches are marked "simulated". |
| `TELEGRAM_CHAT_AMBULANCE`, `TELEGRAM_CHAT_FIRE`, `TELEGRAM_CHAT_POLICE` | The Telegram group each department's messages go to. All three can be the same group. |
| `GEMINI_MODELS` | Optional. The models to try in order (default `gemini-3.5-flash-lite,gemini-3.1-flash-lite`). |
| `GEOCODE_VIEWBOX` | Optional. The map search area (default: Chennai). |

**Telegram setup (about 10 minutes):**
1. In Telegram, message **@BotFather** and send `/newbot`. Put the token it gives you in `TELEGRAM_BOT_TOKEN`. One bot serves every department.
2. Create a group per department (or one group for all), add the bot, and send `/start@<your_bot_username>` in each group.
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser. Each group's chat ID is the negative number next to `"chat":{"id":`. Put the IDs in the `TELEGRAM_CHAT_*` lines.

## Run

```powershell
python scripts/reset_demo.py --yes   # fresh demo data (stop the server first)
python run_server.py
```

- Dashboard: http://localhost:8000
- Caller screen: http://localhost:8000/caller
- API docs: http://localhost:8000/docs

The 3-minute stage script, with fallbacks and likely judge questions, is in [DEMO.md](DEMO.md).

## Tests

```powershell
python tests/test_resq.py          # 24 offline checks: no network, throwaway database
python tests/eval.py               # 30-call accuracy run (uses your Gemini key)
python tests/eval.py --keywords    # the same calls on keyword rules only
```

## Data

Everything is stored locally in SQLite at `backend/resq_continuity.db` (`RESQ_DB_PATH` overrides the path). `scripts/reset_demo.py` recreates it.

| Table | Holds |
|---|---|
| `incidents` | Each incident's full record: fields with provenance, both locations, reasoning, dispatches |
| `call_turns` | The conversation: every caller sentence and every question RESQ asked, in order |
| `coordination_actions` | Each dispatch, one per idempotency key, with delivery and acknowledgement status |
| `timeline_events` | The audit trail: every state change, AI inference, failure and operator action |

## Main API endpoints

| Endpoint | Does |
|---|---|
| `POST /api/incidents` | Start a call (new incident) |
| `POST /api/incidents/{id}/voice-intake` | Add what the caller said: understand, route, pre-alert |
| `GET /api/incidents/{id}/conversation` | The stored conversation |
| `POST /api/incidents/{id}/confirm-location` | Operator confirms the incident location |
| `POST /api/incidents/{id}/approve-action` | Operator confirms a dispatch (sends it) |
| `POST /api/incidents/{id}/merge-into` | Merge a duplicate report into another incident |
| `POST /api/incidents/{id}/disconnect` | Caller hung up or the call dropped |
| `POST /api/transcribe` | Audio to text (Gemini) |
| `GET /api/events/stream` | Live updates (Server-Sent Events) |

The full list is at `/docs` while the server runs.

## Project layout

```
backend/
  main.py                        FastAPI routes, live updates, background pre-alerts and map lookups
  core/orchestrator.py           incident state machine and operator actions
  core/persistence.py            SQLite store
  core/idempotency.py            one dispatch per idempotency key
  agents/voice_agent.py          conversation -> structured fields (Gemini, keyword fallback)
  agents/reasoning_agent.py      completeness, contradictions, possible duplicates
  agents/coordination_agent.py   routing rules -> department proposals
  services/gemini_service.py     typed Gemini extraction and audio transcription
  services/dispatch_service.py   message templates, Telegram delivery, Acknowledge button
  services/geocoding_service.py  map search (suggested pins and "Find on map")
static/index.html, js/           operator dashboard (vanilla JS + Leaflet)
static/caller.html               caller screen
scripts/reset_demo.py            fresh demo database
tests/test_resq.py               offline checks
tests/eval.py                    accuracy evaluation
DEMO.md                          stage script
PLAN.md                          build plan and progress
```

## Safety

RESQ is decision support, not an autonomous dispatcher. Pre-alerts are heads-ups only: **a human confirms every dispatch**, AI corrections never override an operator, and a guessed location is never shown as verified. This prototype never contacts a real agency.
