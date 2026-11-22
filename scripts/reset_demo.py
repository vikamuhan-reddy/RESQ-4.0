"""
Resets the demo database and loads two background incidents so the queue doesn't look empty.
Your live demo calls are NOT pre-loaded: you make those on stage (see DEMO.md).

    python scripts/reset_demo.py          # asks before deleting
    python scripts/reset_demo.py --yes

Stop the server first: Windows keeps the database file locked while it runs.
"""
import argparse
import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# Seeding must never message the real Telegram groups or spend Gemini calls
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["GEMINI_API_KEY"] = ""
DB = os.getenv("RESQ_DB_PATH") or os.path.join(ROOT, "backend", "resq_continuity.db")

BACKGROUND = [
    # (category, language, what the caller said, confirmed place, lat, lon, agency acknowledged?)
    ("Medical Emergency", "en", "An old man collapsed at the Egmore station platform, he's not breathing properly.",
     "Egmore Railway Station", 13.0794, 80.2628, True),
    ("Fire Hazard", "en", "My neighbour's kitchen is on fire, black smoke is coming out. Besant Nagar 2nd Avenue.",
     "Besant Nagar 2nd Avenue", 13.0003, 80.2667, False),
]


async def seed():
    from backend.core.orchestrator import orchestrator
    from backend.agents.voice_agent import voice_agent
    from backend.agents.reasoning_agent import reasoning_agent
    from backend.agents.coordination_agent import coordination_agent

    for category, lang, text, place, lat, lon, acknowledged in BACKGROUND:
        inc = orchestrator.create_incident(category, lang)
        inc = await voice_agent.process_utterance(inc, text, lang)
        orchestrator.confirm_incident_location(inc.incident_id, lat, lon, "Operator-Lead", place)
        inc = reasoning_agent.evaluate_incident(orchestrator.get_incident(inc.incident_id))
        for action in coordination_agent.auto_propose(inc):
            await orchestrator.approve_and_dispatch(inc.incident_id, action.action_id, "Operator-Lead")
            if acknowledged:
                orchestrator.record_agency_acknowledgment(inc.incident_id, action.action_id, "UNIT-17 (seeded)")
        print(f"  seeded {inc.incident_id}: {category} at {place}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="delete without asking")
    args = parser.parse_args()
    if os.path.exists(DB):
        if not args.yes and input(f"Delete {DB} and start a fresh demo database? [y/N] ").strip().lower() != "y":
            print("Nothing changed.")
            return
        try:
            os.remove(DB)
        except PermissionError:
            sys.exit("The database is in use. Stop the server (Ctrl+C in its window) and run this again.")
    print("Fresh demo database:")
    asyncio.run(seed())
    print("Done. Start the server with: python run_server.py")


if __name__ == "__main__":
    main()
