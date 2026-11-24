# RESQ: hackathon submission form answers

Copy each block into the matching field. Fields marked **(fill in)** need your own details.

---

## Participation type
**(fill in)** Team or Individual, whichever matches your registration.

## Team Name
**(fill in)**

## Project title
```
RESQ: AI co-pilot for emergency call-takers
```

## Track
```
Voice — Listen & Act
```

## GitHub Repository
Pick the public RESQ repository under your account (see "Pushing to GitHub" at the end of this file).

## Deployed demo URL
The public HTTPS link from the Cloudflare tunnel, for example `https://<random-words>.trycloudflare.com`. The dashboard is at `/` and the caller screen at `/caller`.

The link works only while the laptop, the server and the tunnel are running, and it **changes every time the tunnel restarts**. To get a fresh one:

```powershell
python run_server.py                                   # terminal 1
cloudflared tunnel --no-autoupdate --url http://localhost:8000   # terminal 2: prints the https://….trycloudflare.com link
```

Keep both terminals open until judging is over.

---

## Project description
```
When someone calls 112 in Chennai, the person answering has to understand a panicking caller, often speaking Tamil or Tamil-English, work out where the emergency is, and pass it to the right department. Details get lost in exactly that step.

RESQ is a co-pilot for that call-taker. The caller speaks on a phone screen; RESQ's voice agent (Google Gemini) turns each statement into structured facts: what happened, injuries, hazards, where the incident is, and whether the caller is even at the scene. It asks the next most useful question back to the caller in Tamil or English. A reasoning agent scores completeness, spots contradictions and flags duplicate callers reporting the same emergency. A coordination agent routes the call to the right departments using fixed rules, not AI, and sends each one a pre-alert on Telegram within seconds. The place is looked up on a map but stays a "suggestion" until the operator confirms it.

A human confirms every dispatch. The department gets a confirmed dispatch with a map link and acknowledges with one tap; a Lyzr agent then writes the crew a five-line handover brief. Every step from every agent is posted live to a BAND room and kept on an audit timeline.

It is built for failure: if Gemini is overloaded the call falls back to keyword rules and is flagged for review, a dropped call keeps the incident open, and duplicate reports are merged so nothing is dispatched twice. On 30 test calls we wrote (Tamil, English, mixed), RESQ routed all 30 correctly, against 16/30 for keyword rules alone. Everything runs in clearly labelled SIMULATION mode; no real agency is contacted.
```

---

## How did you use BAND? (band.ai)
```
BAND is the shared room where RESQ's agents and the humans watching them meet. RESQ joins BAND as its own agent through the band-sdk: with just an account API key it registers a "RESQ" agent, opens a "RESQ live feed" room and adds the operator to it.

From then on every step of every call is posted to that room as it happens, labelled by the agent that did it: the Voice Intelligence Agent's extraction, the Reasoning Agent's assessment, the Coordination Agent's routing, the Dispatch Service's pre-alerts and confirmed dispatches, department acknowledgements, and the Lyzr agent's crew brief. Failures (for example Gemini overloaded) are flagged with a warning so a supervisor sees them immediately.

RESQ also listens in the room: anyone can type "@RESQ status" to get the open incidents, or "@RESQ <incident id>" for one incident's category, urgency, location, dispatch status and what is still unknown. BAND gives a supervisor a live, replayable view of the multi-agent pipeline without opening the dashboard.
```

## How did you use AdaL? (adalagent.ai)
```
We did not use AdaL in the final build. AdaL is a desktop video agent that currently ships for macOS, and our team builds on Windows, so we could not run it in the time available. We recorded our pitch directly instead. AdaL would be our choice for a polished launch film for RESQ in a next iteration.
```

## How did you use Finch? (finchtech.ai)
```
We did not use Finch in the final build. We looked at publishing RESQ's triage logic (category, urgency and department routing rules) as a reusable Finch Skill, but publishing requires setting up a Finch wallet identity and the Finch CLI, which we could not complete within the hackathon. Packaging the routing table and the Tamil/English intake prompt as a Finch Skill is a planned next step.
```

## How did you use Lyzr? (lyzr.ai)
```
Lyzr powers RESQ's Handover Agent. After the operator confirms a dispatch, RESQ calls an agent on Lyzr Agent Studio through its inference API with the dispatch record and the call transcript, and gets back a five-line brief for the responding crew: what happened and how urgent it is, where to go and whether that location is confirmed or only suggested, patients and hazards to expect, and the one thing to verify first.

The brief is sent as a reply in the department's Telegram thread, shown on the dispatch card in the dashboard (marked as AI-written), and posted to the BAND room. Only a Lyzr API key is needed: RESQ finds its "RESQ Handover Agent" on the account or creates it on first use, and keeps one Lyzr session per incident.

We designed it so the AI never slows or replaces the dispatch: the fixed dispatch message goes out first, the brief follows a few seconds later, the prompt forbids inventing locations or injuries, and if Lyzr fails the timeline shows it while the dispatch stands.
```

## How did you use Agent37? (agent37.com)
```
We tried Agent37 for hosting the demo: the caller screen needs HTTPS for the phone's microphone and location, and an Agent37 sandbox gives a public HTTPS URL. We wrote a deploy script against the Agent37 API (find or create a sandbox, upload the code, start the server, open a public port), and our API key authenticated, but creating a sandbox requires a funded workspace balance, which we did not have. We removed that path and kept the app runnable locally. Agent37 remains the hosting option we would use with a funded account.
```

## What problems did you face during building?
```
1. Unreliable AI under load. Gemini often answered "503 high demand" or timed out, and older models we started with were retired mid-build. We added a model fallback chain, a quick retry on overload, and a keyword-rule fallback that flags the incident for operator review, so a call is never lost when the AI is down.

2. Mixed-language callers. Real callers mix Tamil and English and may not be at the scene. We send Gemini the whole speaker-labelled conversation so it doesn't re-ask questions, and extract the incident location and the caller's location separately.

3. Trustworthy locations. A spoken landmark is not a map pin. Map search results are shown only as suggestions until an operator confirms them; we also had to switch map tiles when our first provider started requiring a key.

4. Statements going to the wrong incident. Early on, a new caller's words could be added to whichever incident was selected on screen; we separated "the live call" from "the selected incident".

5. Duplicate callers. Several people report the same accident; we flag reports at the same place within 15 minutes and let the operator merge them, cancelling the duplicate's pending dispatches.

6. Integrations. Telegram acknowledgements needed no public URL, so we used long-polling; BAND rejected our account key on agent endpoints until we had RESQ register its own agent; browsers without a Tamil voice cannot speak the follow-up question (Microsoft Edge works).
```

---

## Pushing to GitHub

The form only lists public repositories under your own GitHub account. The original repo (`Gedipudidarshani/RESQ-4.0`) belongs to a teammate, and your account has read-only access to it, so the project goes to a repo under your account. Your keys stay out of it: `.env` and `backend/band_agent.json` are git-ignored.
