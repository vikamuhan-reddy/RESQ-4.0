"""
RESQ evaluation: runs tests/eval_calls.jsonl through the real intake pipeline and prints accuracy.
The 30 calls are written by the team (not real emergency calls); labels follow what the caller said.

    python tests/eval.py              # Gemini (needs GEMINI_API_KEY in .env)
    python tests/eval.py --keywords   # keyword-rule fallback only, as a baseline
"""
import argparse
import asyncio
import json
import os
import sys
import tempfile
import time

os.environ["RESQ_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "eval.db")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(ROOT, ".env"))
parser = argparse.ArgumentParser()
parser.add_argument("--keywords", action="store_true", help="disable Gemini, measure the keyword fallback")
parser.add_argument("--delay", type=float, default=None, help="seconds between calls (free-tier rate limits)")
args = parser.parse_args()
if args.keywords:
    os.environ["GEMINI_API_KEY"] = ""
delay = args.delay if args.delay is not None else (0 if args.keywords else 3)

from backend.core.orchestrator import orchestrator  # noqa: E402
from backend.core.persistence import db_engine  # noqa: E402
from backend.agents.voice_agent import voice_agent  # noqa: E402
from backend.agents.coordination_agent import coordination_agent  # noqa: E402
from backend.models.incident import IncidentRecord, FieldProvenance  # noqa: E402
from backend.models.enums import IncidentCategory, VerificationStatus  # noqa: E402

METRICS = ["category", "routing", "injured", "caller_on_scene", "location"]


def routes_for(category: str, injured: bool):
    inc = IncidentRecord(category=IncidentCategory(category))
    if injured:
        inc.fields["reported_injuries"] = FieldProvenance(field_name="reported_injuries", current_value="x")
    return sorted(t for t, _ in coordination_agent.route(inc))


async def run_case(case):
    inc = orchestrator.create_incident("Other Emergency", case["lang"])
    t0 = time.time()
    inc = await voice_agent.process_utterance(inc, case["text"], case["lang"])
    seconds = time.time() - t0
    used_ai = any(e.event_type == "AGENT_INFERENCE" and "Gemini" in e.summary for e in db_engine.get_events(inc.incident_id))

    loc = inc.locations.incident_location
    loc_text = "" if loc.verification_status == VerificationStatus.MISSING else loc.description.lower()
    got_routes = sorted(t for t, _ in coordination_agent.route(inc))
    # "injured": null means the call is ambiguous (e.g. people trapped): either routing is accepted, injuries not scored
    allowed_routes = [routes_for(case["category"], False), routes_for(case["category"], True)] if case["injured"] is None \
        else [routes_for(case["category"], case["injured"])]

    checks = {
        "category": inc.category.value == case["category"],
        "routing": got_routes in allowed_routes,
        "caller_on_scene": (not inc.locations.is_separated) == case["caller_on_scene"],
        "location": any(k.lower() in loc_text for k in case["location_keywords"]) if case["location_keywords"] else loc_text == "",
    }
    if case["injured"] is not None:
        checks["injured"] = ("reported_injuries" in inc.fields) == case["injured"]
    got = {"category": inc.category.value, "routes": got_routes, "injured": "reported_injuries" in inc.fields,
           "on_scene": not inc.locations.is_separated, "location": loc_text}
    return checks, got, seconds, used_ai


async def main():
    cases = [json.loads(line) for line in open(os.path.join(ROOT, "tests", "eval_calls.jsonl"), encoding="utf-8") if line.strip()]
    mode = "keyword rules only" if args.keywords else "Gemini (keyword fallback on failure)"
    print(f"RESQ eval: {len(cases)} calls, {mode}\n")
    passed = {m: 0 for m in METRICS}
    scored = {m: 0 for m in METRICS}
    ai_answers, times, results = 0, [], []
    for i, case in enumerate(cases):
        if i and delay:
            await asyncio.sleep(delay)
        checks, got, seconds, used_ai = await run_case(case)
        results.append((checks, got))
        ai_answers += used_ai
        times.append(seconds)
        for m, ok in checks.items():
            scored[m] += 1
            passed[m] += ok
        fails = [m for m, ok in checks.items() if not ok]
        status = "ok  " if not fails else "MISS"
        detail = "" if not fails else "  <- " + ", ".join(f"{m}: got {got[{'routing': 'routes', 'caller_on_scene': 'on_scene'}.get(m, m)]!r}" for m in fails)
        print(f"{status} {case['id']:<6} {seconds:4.1f}s {'AI ' if used_ai else 'KW '} {case['category']:<24}{detail}")

    print("\n| Metric | Correct | Accuracy |\n|---|---|---|")
    for m in METRICS:
        print(f"| {m.replace('_', ' ')} | {passed[m]}/{scored[m]} | {100 * passed[m] / scored[m]:.0f}% |")
    away = [c for c in cases if not c["caller_on_scene"]]
    away_ok = sum(1 for c, (checks, *_rest) in zip(cases, results) if not c["caller_on_scene"] and checks["caller_on_scene"])
    print(f"| caller away detected (of callers not at the scene) | {away_ok}/{len(away)} | {100 * away_ok / len(away):.0f}% |")
    times.sort()
    print(f"\nAI answered {ai_answers}/{len(cases)} calls (the rest fell back to keyword rules). "
          f"Median time per call {times[len(times) // 2]:.1f}s, slowest {times[-1]:.1f}s.")


asyncio.run(main())
