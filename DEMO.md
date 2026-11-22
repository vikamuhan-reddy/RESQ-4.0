# RESQ demo script (3 minutes)

## Setup (do this 15 minutes before)

1. Stop the server if it's running, then reset the demo data:
   ```powershell
   python scripts/reset_demo.py --yes
   python run_server.py
   ```
2. Open **Microsoft Edge**. Edge has a Tamil voice; Chrome on this laptop doesn't.
   - Left half of the screen: **dashboard** at http://localhost:8000
   - Right half: **caller screen** at http://localhost:8000/caller
3. Allow microphone and location when the caller screen asks.
4. Phone: Telegram open on the **RESQ** group, notifications **on**, volume up. Give it to a teammate, who taps **Acknowledge** when the message arrives.
5. **Warm-up call:** make one throwaway call to check Gemini and the mic. Use a place that's **not** in the script (e.g. "fire in Adyar"). Then repeat step 1 (stop, reset, start), or the warm-up call will show up in the duplicate check.
6. Have the **backup video** open in another tab.

## The script

| Time | Do | Say |
|---|---|---|
| 0:00–0:20 | Dashboard visible | "112 gives India one emergency number. But the person answering still has to understand a panicking caller, often in Tamil, get the location right, and forward it to the right department. That's where details get lost. RESQ is a co-pilot for that call-taker." |
| 0:20–0:50 | **Caller screen:** tap **Call 112** (Tamil selected). Tap the mic and say, or type: *"Anna, Gemini flyover kitta accident aayiduchu, rendu peru ku blood varudhu, naan bus la irukken"*. Tap again to send. | "A caller on a bus sees an accident and speaks Tamil-English." |
| 0:50–1:10 | Point at the dashboard: category, injuries, caller **not at the scene**, the conversation panel, Ambulance + Traffic Police proposed. The Tamil question is spoken on the caller screen. **The phone buzzes: a PRE-ALERT.** | "In about three seconds it understood: road accident, two bleeding, and the caller is *not* at the scene; he's on a bus. It asks the next question in Tamil. Rules, not AI, pick the departments, and the ambulance team already has a pre-alert." |
| 1:10–1:30 | The **amber pin** has appeared on Gemini Flyover by itself. Click it, then **Confirm incident location here**. It turns red. | "It found the place on the map by itself, but marks it as a suggestion. One click from the operator confirms it." |
| 1:30–1:55 | Click **Confirm Dispatch** on the Ambulance card. The phone buzzes again with the **CONFIRMED DISPATCH** (a reply to the pre-alert, with a map link). The teammate taps **Acknowledge**. | "A human confirms. The ambulance team gets the confirmed dispatch with the exact location, and acknowledges from their phone." The card and the caller screen both flip to *acknowledged*. Point at the timer: "Department notified in under a minute." |
| 1:55–2:20 | Caller screen: tap **Hang up**, then **New call**, then switch to English and type: *"There's a fire in a shop near Koyambedu market and one man has burns on his arm"*. | "One call, two departments: fire *and* ambulance, because someone is hurt." |
| 2:20–2:40 | New call, Tamil: *"Gemini flyover signal la accident, oru car um bike um, naan auto la irukken"*. Dashboard: **Possible duplicate reports** shows the first call; click **Same emergency: merge**. | "A second person reports the same accident. RESQ flags it, and the operator merges it: its pending dispatches are cancelled and the department gets a CANCELLED note, so the same accident isn't dispatched twice." |
| 2:40–3:00 | Scroll to the README's evaluation table, or a slide of it. | "On 30 test calls we wrote in Tamil, English and mixed, it routed every one correctly, against 53% for keyword rules. It's a small synthetic set, and real call recordings are our next step. If the AI fails, the incident is flagged and keyword rules take over, so nothing is lost." |

## If something breaks on stage

| Problem | Do |
|---|---|
| Gemini slow or "overloaded" | It falls back to keyword rules by itself; the timeline says "Keyword rules (AI unavailable)". Say: "That's the failure handling working." Resubmit once. |
| No Tamil voice | Read the question aloud: "In a real call system this is spoken to the caller." |
| Mic not picking up | Type the same sentence in the caller screen's text box. |
| Telegram slow, or teammate misses the tap | Click **Simulate ACK** on the dashboard card. |
| No amber pin appears | The place had no map match: click **Find on map**, or click the right spot on the map. |
| Typing on the dashboard instead of the caller screen | Fine: the statement box starts a **new call** ("● Live call …"). Click **End call** before the next caller. |
| No internet at all | Play the backup video. |

## Likely questions

- **"Doesn't 112 already do this?"** 112 unifies the *number*. We help the call-taker *understand and route* the call correctly in seconds. It plugs into the existing system as an assistant.
- **"What if the AI is wrong?"** The AI never dispatches. Rules choose the department and a human approves every dispatch. Every field shows where it came from and whether anyone verified it, and operator corrections are never overwritten.
- **"How accurate is it?"** On 30 calls we wrote: 100% category and routing, 97% location, against 60%, 53% and 20% for keyword rules. That's a small synthetic set, so real recordings are the next step.
- **"Why Telegram?"** It stands in for each department's dispatch system. Delivery confirmation and the acknowledgement are real round trips. Integrating with real dispatch systems is the next step.
- **"Location?"** The caller's words are never turned into a pin automatically; the operator confirms it on the map. The caller's phone can share its location too.
- **"Privacy?"** The prototype stores data in a local database. Transcripts go to Gemini for understanding. Production would need data agreements or an on-premise model.
