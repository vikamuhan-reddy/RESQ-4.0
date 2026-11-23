# RESQ: screen-recorded pitch script

The submission page records your **whole screen** with your camera in a corner. You talk the judges through RESQ and demo it live. The recording must be at least 1 minute and at most 7. This script runs about **5 minutes**.

Read it through once, then do one practice run before recording.

---

## Part 1: Set up (about 10 minutes, before you record)

### 1. Start RESQ

Open a terminal in the project folder (`RESQ-4.0`) and run:

```powershell
.venv\Scripts\activate
python scripts/reset_demo.py --yes      # fresh demo data (the server must be stopped)
python run_server.py
```

Wait until the terminal shows `Uvicorn running on http://127.0.0.1:8000`. A few seconds later it should also show `[band] connected as agent ...`. Leave this terminal open; don't close it while recording.

### 2. Open these windows in Microsoft Edge

Use **Edge**, because it has a Tamil voice for the spoken questions.

| # | What | Address | Check |
|---|---|---|---|
| A | **Dashboard** (main window, large) | `http://localhost:8000` | The four chips at the top right (Gemini, Lyzr, BAND, Telegram) are **green**. Two demo calls are in the queue. |
| B | **Caller screen** (a separate, narrow window, like a phone) | `http://localhost:8000/caller` | A green **Call 112** button; language set to **தமிழ்** (Tamil). |
| C | **Telegram**: the department group | Telegram Desktop, or `web.telegram.org`, open on the **RESQ** group | You can see the group's latest messages. |
| D | **BAND**: the agent room | `app.band.ai`, then **Chats**, then **RESQ live feed** | The room shows "RESQ is connected…". |
| E | **Submission page** | The hackathon submit page | Keep it in its own window. This is where recording starts and stops. |

**Arrange the screen:** dashboard (A) on the left, about two-thirds of the screen; caller screen (B) as a narrow window on the right. Keep Telegram (C) and BAND (D) one click away on the taskbar.

### 3. Tidy up
- Turn on **Focus assist / Do not disturb** in Windows so no pop-ups appear.
- Close other tabs and apps that show personal information.
- Set the browser zoom to 90–100% so the whole dashboard is visible.
- Test your microphone. Speak clearly and a bit slower than usual.

### 4. Practice once
Run the whole script once without recording. Afterwards, reset the data: stop the server (Ctrl+C), run `python scripts/reset_demo.py --yes`, then start `python run_server.py` again.

---

## Part 2: Start the recording

1. Go to the **submission page** window (E) and click **Start recording**.
2. In the browser picker choose **Entire Screen**. Do **not** pick a single Chrome tab, because a tab share stops when you switch windows.
3. Allow the **camera** and **microphone**.
4. Switch to the dashboard (A) and begin the script.
5. Don't press the browser's **Stop sharing** before 1:00, or the take is thrown away. When you finish, go back to the submission page and click **Submit recording**.

---

## Part 3: The script

**DO** is what you click. **SAY** is what you say (in your own words is fine).

### 0:00–0:25 · The problem
**DO:** The dashboard (A) is on screen.
**SAY:**
> "Hi, we're team ___. This is RESQ. When someone calls 112 in Chennai, the person answering has to understand a panicking caller, often in Tamil or a Tamil-English mix, figure out where the emergency is, and pass it to the right department. That's where details get lost. RESQ is an AI co-pilot for that call-taker."

### 0:25–0:50 · The command centre
**DO:** Point at each part of the dashboard with the mouse as you name it.
**SAY:**
> "This is the operator's command centre. On the left, the live queue: every call, colour-coded by urgency. At the top, live numbers: open calls, critical ones, dispatches waiting for a human, and units notified. And these chips show our AI services are live: Gemini understands the call, Lyzr writes crew briefs, BAND is where our agents report, and Telegram stands in for each department's dispatch system."

### 0:50–1:40 · A real call, in Tamil-English
**DO:**
1. Go to the caller screen (B). Check **தமிழ்** (Tamil) is selected, then tap **Call 112**.
2. Tap the **mic** and say (or type in the text box): *"Anna, Gemini flyover kitta accident aayiduchu, rendu peru ku blood varudhu, naan bus la irukken"*. Tap the mic again (or the send arrow) to send.
3. Look back at the dashboard: the new call appears at the top of the queue. Click it if it doesn't open by itself.

**SAY:**
> "Here's a caller on a bus who sees an accident. He speaks Tamil-English: 'there's been an accident near Gemini flyover, two people are bleeding, I'm on a bus'."

**DO:** Point at the incident header (Road Accident, CRITICAL), the **Conversation** panel with **Ask the caller next**, the **Location** card saying *Caller away from scene*, and the **Dispatch** cards.
**SAY:**
> "In about two seconds our voice agent understood it: road accident, two people bleeding, critical. And notice: it worked out the caller is not at the scene, he's on a bus, so his location and the accident's location are kept separate. It asks the next most useful question, in Tamil, and the caller hears it spoken. The departments, Ambulance and Traffic Police, were picked by fixed rules, not by the AI."

### 1:40–2:00 · Pre-alert in seconds
**DO:** Click over to Telegram (C). Show the new **RESQ PRE-ALERT** message.
**SAY:**
> "And the ambulance team already has a pre-alert on their phone, before anyone has even confirmed. It says clearly that an operator is still reviewing it."

### 2:00–2:25 · Location you can trust
**DO:** Back to the dashboard. Scroll to **Location**. An **amber pin** is on Gemini Flyover. Click it, then click **Confirm incident location here**. The pin turns red and the chip says **Confirmed**.
**SAY:**
> "RESQ found the place on the map by itself, but it's amber: only a suggestion. AI never decides where an ambulance goes. One click from the operator confirms it."

*If no amber pin appears, click **Find on map** and pick the right result, or click the right spot on the map.*

### 2:25–3:05 · Human confirms, department acknowledges, Lyzr briefs the crew
**DO:**
1. Scroll to **Dispatch**. On the **Ambulance (108)** card click **Confirm dispatch**.
2. Click over to Telegram (C): the **CONFIRMED DISPATCH** message has arrived, with a map link and an **Acknowledge** button. Click **Acknowledge** (or have a teammate tap it on their phone).
3. Back on the dashboard: the card's steps fill up to **Acknowledged**, and a purple **Crew brief · written by Lyzr agent** appears on the card. Point at the green timer at the top: *First department notified in …*

**SAY:**
> "A human confirms every dispatch. The ambulance team gets the confirmed dispatch with the exact location and acknowledges with one tap, and the dashboard updates live. Then our Lyzr agent writes the crew a five-line brief: what happened, where to go, what injuries and hazards to expect, and the first thing to check. It's marked as AI-written, and it never delays the dispatch itself. From the call to the first department notified: under a minute."

### 3:05–3:35 · The agents, working together in BAND
**DO:** Click over to BAND (D), the **RESQ live feed** room. Scroll through the latest messages. In the message box type `@RESQ status` and send. RESQ replies with the open incidents.
**SAY:**
> "RESQ is a team of agents: a voice agent, a reasoning agent, a coordination agent, dispatch, and the Lyzr handover agent. Every step they take is posted live into this BAND room, so a supervisor can watch the whole pipeline. They can also ask RESQ directly: '@RESQ status' lists every open emergency."

*If RESQ doesn't reply within ~10 seconds, just carry on: the live feed above already shows the agents at work.*

### 3:35–4:15 · A second caller reporting the same accident
**DO:**
1. On the caller screen (B) tap **Hang up**, then **New call**, then **Call 112**.
2. Say or type: *"Gemini flyover signal la accident, oru car um bike um, naan auto la irukken"*. Send it.
3. On the dashboard open this new call. Under **Reasoning agent**, **Possible duplicate reports** shows the first call. Click **Same emergency · merge** and confirm.

**SAY:**
> "In real emergencies many people call about the same accident. RESQ flags that this report is at the same place as the first one. The operator merges them, the duplicate's pending dispatches are cancelled, and the department gets a cancellation note, so one accident is never dispatched twice."

### 4:15–4:40 · Built for failure
**DO:** Open the first call again. Click **Drop call** (top of the incident). The chip turns purple: *Line dropped*. Point at **Agent activity**, colour-coded by agent.
**SAY:**
> "Emergencies are where things fail. If the caller's line drops, the incident stays open with everything we already know. If Gemini is overloaded, RESQ falls back to keyword rules and flags the call for review, so nothing is ever lost. And every step from every agent is on this audit trail."

### 4:40–5:00 · Results and close
**DO:** Back on the dashboard header, or show the README's **Evaluation** table if you have it open.
**SAY:**
> "We tested RESQ on 30 calls we wrote in Tamil, English and mixed: it routed all 30 to the right departments, against 16 for keyword rules alone. It's a small synthetic set, and real call recordings are our next step. Everything runs in simulation mode; no real agency is contacted. RESQ: listen, understand, and get the right help moving. Thank you."

**DO:** Switch to the submission page (E) and click **Submit recording**.

---

## If something goes wrong while recording

Keep talking. Each of these is a feature, not a failure.

| Problem | What to do and say |
|---|---|
| Gemini is slow or "overloaded" | It falls back to keyword rules by itself, and the timeline says so. Say: "That's our failure handling working: Gemini is busy, so keyword rules took over and the call is flagged for review." |
| The question isn't spoken aloud | You're probably not in Edge. Read the question out: "In a real call it is spoken to the caller in Tamil." |
| The microphone doesn't pick you up | Type the same sentence in the caller screen's text box and press send. |
| Telegram is slow, or Acknowledge doesn't work | On the dispatch card click **Simulate department ACK**. |
| No amber pin on the map | Click **Find on map**, or click the right spot on the map yourself. |
| The Lyzr brief doesn't appear | Wait 5–10 seconds, or click the call in the queue to refresh. If it's still missing, say: "The brief follows the dispatch; the dispatch itself never waits for it." |
| A chip at the top is grey | That service's key is missing in `.env`. Restart the server after fixing it, or just carry on: RESQ works without it. |
| You make a mistake | Keep going. If it's bad, stop after 1:00, then reset (Ctrl+C, `python scripts/reset_demo.py --yes`, `python run_server.py`) and record again. |
