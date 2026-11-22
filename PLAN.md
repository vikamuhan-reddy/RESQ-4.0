# RESQ 4.0 — Implementation Plan

**The demo we are building toward (3 minutes):**
1. A teammate "calls" by speaking into the mic in panicked Tamil-English.
2. The dashboard fills in live: what happened, injuries, location as heard.
3. Something is missing, so RESQ asks back by voice in Tamil. The answer updates the record.
4. The operator picks the right location from 2–3 map candidates.
5. RESQ routes to the right department(s); the operator clicks Approve.
6. **A department phone on the table buzzes** with the dispatch message. A timer shows the seconds taken.

**Rules:** every phase ends with a working demo, so we can stop at any phase. Every step adds one check, and no step is done until its check passes and `python tests/test_resq.py` is still green.

---

## Before we start: decisions needed from you

| # | Decision | Needed for |
|---|---|---|
| D1 | Deadline and team size (this sets the cut line at the bottom) | Everything |
| D2 | A Gemini API key (free from Google AI Studio) | Phase 2 |
| D3 | A Telegram bot from @BotFather, plus one group per department (Ambulance, Fire, Police) with teammates' phones in them, about 10 min | Phase 3 |
| D4 | The city to search locations in (assumed: **Chennai**) | Phase 4 |
| D5 | A separate "caller" screen on a second phone or laptop? (optional) | Phase 5 |

---

## Phase 1 — Make it correct (~2–3 h)
*Things a judge could break during the live demo.*

**1.1 All state changes go through one place**
- Route every state change through `orchestrator.transition_state`. Today 8 places set `incident.state` directly (voice/reasoning/coordination agents plus 5 in the orchestrator). Adjust `VALID_TRANSITIONS` to the real flow.
- Approve requires the action to be `CREATED`. ACK requires it to be `SENT` *and* operator-approved.
- ✅ Check: ACK on an unapproved action fails; approving on a `CLOSED` incident fails.

**1.2 Proper HTTP errors**
- Add two exception types (`NotFound`, `Conflict`) and one handler in `main.py`, so these return 404/409 instead of 500.
- ✅ Check: an unknown incident ID returns 404.

**1.3 Safe rendering**
- Use `textContent` (or one small `esc()` helper) everywhere `app.js` and `map.js` insert caller, AI or operator text with `innerHTML`: queue, timeline, actions, reasoning, map popups.
- ✅ Check: an override value of `<img src=x onerror=alert(1)>` displays as plain text.

**1.4 Small bugs**
- Acknowledge reads `operator_id` from the request body; today the frontend sends it there and the backend ignores it.
- Show the green "verified" badge only for `INDEPENDENTLY_VERIFIED`. Today `MISSING` shows green too.
- An empty action list no longer wipes the simulation notice.

---

## Phase 2 — Real understanding (~4–6 h) ⭐ core

**2.1 Gemini extraction, done right**
- Move from the deprecated `google-generativeai` to the `google-genai` SDK, use a current Flash model, and use structured output (response schema = a Pydantic model) so we never parse JSON by hand.
- Schema: `category, injuries, affected_count, hazards[], incident_location_text, caller_location_text, caller_on_scene, missing[], next_question_en, next_question_ta, confidence`.
- Send the **whole conversation so far**, not just the last sentence. That also fixes the bug where a follow-up resets the category.
- Make `process_utterance` async, call Gemini with `await asyncio.wait_for(..., 8)`, and delete the thread-pool code. On timeout or error, call `orchestrator.handle_ai_service_failure` and fall back to keyword rules, clearly labelled.
- The AI never overwrites a field the operator has corrected.
- ✅ Check: 10 sample transcripts (EN/TA/mixed) give sensible JSON. With a wrong API key the server stays responsive and the incident is flagged for review.

**2.2 Speech input**
- `/api/transcribe`: new SDK, audio sent inline (nothing left stored at Google), 10 MB limit, async.
- Keep browser speech recognition for live captions.
- ⚠️ **Day-1 risk check:** record 5 real Tamil and Tamil-English clips. If transcription is poor, try Sarvam AI's speech-to-text instead (decision point).
- ✅ Check: speaking a Tamil report fills the transcript correctly.

**2.3 Keyword fallback becomes "AI down" mode only**
- Fix "building collapsed" being classed as Medical.
- Fix the number traps ("12 people" read as 2, "nobody hurt" read as injured).
- Classify unknown reports as `Other`, not Road Accident.
- ✅ Check: the misclassification cases from the review are in the test and pass.

---

## Phase 3 — Routing and delivery (~3–4 h) ⭐ wow moment

**3.1 Routing by rules, not AI**
`coordination_agent.recommend_actions` already exists but is never called. Turn it into the routing table and call it after every extraction. It auto-creates one proposal per department per incident.

| Category | Departments |
|---|---|
| Road accident | Ambulance 108 (if injured) + Traffic Police |
| Fire | Fire 101 (+ Ambulance if injured) |
| Medical | Ambulance 108 |
| Gas leak / Collapse | Fire 101 + Ambulance 108 |
| Crime / violence | Police 100 (+ Ambulance if injured) |
| Other / unclear | Operator decides |

✅ Check: a table-driven test covers every row.

**3.2 Dispatch message from a fixed template (not AI-written)**
Contents: type, location (with a map link only if the location is confirmed), injuries, hazards, caller callback number, what's still unknown, incident ID, and a `SIMULATION` tag.

**3.3 Telegram delivery**
- On Approve, send the message to that department's group (bot token and chat IDs in `.env`, sent with `httpx`).
- Mark the action `SENT` only if Telegram confirms delivery. Otherwise mark it `FAILED` and show the reason.
- ✅ Check: clicking Approve makes the right phone buzz.

**3.4 (stretch) Department acknowledges from Telegram**
An "Acknowledge" button in the message, read by background polling (no public URL needed). The action becomes `ACKNOWLEDGED` and the dashboard updates live.

---

## Phase 4 — Location you can trust (~2–3 h)

**4.1** Delete the fixed `LANDMARK_COORDS` coordinates. The incident location stays as text until someone confirms it.

**4.2** Look up the spoken landmark with Nominatim, limited to the city (`viewbox` + `bounded`, top 3, at most 1 request per second, real User-Agent). Return candidates and don't place a pin automatically.

**4.3** Candidates appear as small markers. When the operator clicks one, coordinates are set, status becomes `INDEPENDENTLY_VERIFIED` and the history is kept. Only then does the map show the incident pin, and only then does the dispatch message include the map link.

**4.4** Use the browser's `navigator.geolocation` for the caller's own location, with real coordinates and a new source value `DEVICE_GPS`.

✅ Check: "near the bridge" shows no pin until the operator picks a candidate.

---

## Phase 5 — Ask-back loop (~2 h)

**5.1** After each extraction, show `next_question` and speak it in the caller's language (`voiceInterface.speak` already exists). The answer is recorded, added to the incident, and extraction runs again.

**5.2 (optional, D5)** A caller screen, `static/caller.html`: a big mic button plus the spoken questions, on a phone or second laptop. The operator dashboard stays on the main screen.

✅ Check: a missing location triggers a spoken Tamil question, and the answer fills the location.

---

## Phase 6 — Prove it (~2–3 h)

**6.1 Evaluation set**
- `tests/eval_calls.jsonl`: 30 calls (10 Tamil, 10 English, 10 mixed; include vague locations, dropped calls and non-emergencies), each with the expected category, departments and location text.
- `tests/eval.py` prints the accuracy. **The real numbers go in the README.**

**6.2 Time-to-dispatch timer** for each incident, from call start to department notified.

**6.3 Duplicate callers**
- Treat reports as the same incident if confirmed coordinates are within 500 m (or the landmark text matches) **and** they're within 15 minutes.
- The operator links them; nothing merges automatically. A second report doesn't trigger a second dispatch.

**6.4 Dropped call**
On disconnect, propose routing with whatever is known and flag what's missing.

---

## Phase 7 — Demo and pitch (~2 h)
- A seed/reset script with the 3 demo calls ready.
- Rehearse the 3-minute script at least 3 times. **Record a backup video** in case Wi-Fi or the API fails on stage.
- Offline fallback: if Gemini fails live, a typed transcript plus keyword mode still routes.
- Final README: status table plus the real evaluation numbers.

---

## 24-hour schedule (solo)

| Hours | Do | Why it's in | Status |
|---|---|---|---|
| 0–2 | 1.1, 1.2, 1.3 | Judges can't break the demo | ✅ done (+1.4) |
| 2–6 | 2.1 + 2.3 (only the "unknown → Other" fix) | The core: real understanding | ✅ done (+2.2 transcribe ported) |
| 6–9 | 3.1, 3.2, 3.3 | The wow moment: a phone buzzes | ✅ code done; live Telegram test waits on D3 |
| 9–10 | 4.1 (delete fake pins, ~10 min) + 5.1 (spoken follow-up) | Safety, and visible "listening" | ✅ done |
| 10–12 | 6.1 evaluation set, real numbers in README | Answers "how do you know it works?" | ✅ done |
| 12–14 | Buffer: bugs, then 6.2 timer / 6.4 dropped-call routing if time | Cheap extras after 3.1 | ✅ 6.2, 6.4, plus 4.2/4.3 (operator confirms location on map); Telegram live-tested |
| extra | 3.4 Telegram Acknowledge, 6.3 duplicate merge, 5.2 caller screen + 4.4 caller GPS, demo kit (reset script + DEMO.md) | Requested after the plan was done | ✅ done; live Telegram tap still to test with you |
| 14–20 | **Sleep** | A tired demo loses |
| 20–24 | Phase 7: seed script, rehearse ×3, backup video, slides | The demo is what gets judged |

**Cut for now:**
- 1.4
- 2.2: Chrome's built-in speech recognition already supports Tamil (`ta-IN`), so the transcribe rework waits.
- 3.4, 4.2–4.4, 5.2, 6.3

Add any of these back only if we're ahead of schedule.
