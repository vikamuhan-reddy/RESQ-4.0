"""
RESQ 4.0 smoke test: intake -> reasoning -> idempotent proposal -> override -> disconnect -> restart.
Runs against a throwaway DB so the demo DB stays clean.
"""
import sys
import os
import asyncio
import tempfile

# Must be set before backend modules are imported (persistence reads it at import time)
os.environ["RESQ_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
# Keyword path only, so results are deterministic. Empty (not unset) so load_dotenv() won't refill it from .env
os.environ["GEMINI_API_KEY"] = ""
for _k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_AMBULANCE", "TELEGRAM_CHAT_FIRE", "TELEGRAM_CHAT_POLICE",
           "LYZR_API_KEY", "LYZR_AGENT_ID", "BAND_AGENT_ID", "BAND_API_KEY"):
    os.environ[_k] = ""  # never message real Telegram groups or call Lyzr/BAND from tests, whatever .env says
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import types
import httpx
from fastapi.testclient import TestClient
from backend.main import app
from backend.core.orchestrator import orchestrator, Conflict, NotFound
from backend.agents.voice_agent import voice_agent
from backend.agents.reasoning_agent import reasoning_agent
from backend.agents.coordination_agent import coordination_agent
from backend.core.persistence import PersistenceEngine, db_engine
from backend.models.enums import IncidentState, VerificationStatus, ConnectionState, ActionStatus, IncidentCategory
from backend.models.incident import IncidentRecord, FieldProvenance
from backend.services.gemini_service import Extraction
from backend.services import dispatch_service
import backend.agents.voice_agent as voice_agent_module


def assert_raises(exc, fn, *args):
    try:
        fn(*args)
    except exc:
        return
    raise AssertionError(f"{fn.__name__} did not raise {exc.__name__}")


def test_full_pipeline():
    print(">>> 1. Intake (Tamil, remote caller)...")
    inc = orchestrator.create_incident("Road Accident", "ta")
    assert inc.state == IncidentState.RECEIVED
    utterance = "வணக்கம், அண்ணா மேம்பாலம் அருகே ஒரு பெரிய விபத்து. இரண்டு பேர் பலத்த காயமடைந்துள்ளனர். நான் இங்க இல்ல, என் அலுவலகத்திலிருந்து பார்க்கிறேன்."
    inc = asyncio.run(voice_agent.process_utterance(inc, utterance, "ta"))
    assert inc.category.value == "Road Accident"
    assert "reported_injuries" in inc.fields
    assert inc.fields["reported_injuries"].verification_status == VerificationStatus.CALLER_REPORTED
    assert inc.locations.is_separated is True
    assert inc.locations.incident_location.verification_status == VerificationStatus.UNCERTAIN

    print(">>> 2. Reasoning...")
    inc = reasoning_agent.evaluate_incident(inc)
    assert inc.reasoning.completeness_score > 0.0
    assert len(inc.reasoning.missing_critical_fields) > 0

    print(">>> 3. Idempotent proposal...")
    a1 = coordination_agent.create_action_proposal(inc, "DISPATCH_EMS", "108 Ambulance", custom_idempotency_key="TEST-IDEMP-001")
    a2 = coordination_agent.create_action_proposal(inc, "DISPATCH_EMS", "108 Ambulance", custom_idempotency_key="TEST-IDEMP-001")
    assert a1.action_id == a2.action_id

    print(">>> 4. Operator override keeps history...")
    inc = orchestrator.operator_override_field(
        incident_id=inc.incident_id,
        field_name="reported_injuries",
        new_value="Three people injured (one critical)",
        reason="Verified on CCTV camera pole 14",
        operator_id="Operator-Lead"
    )
    f = inc.fields["reported_injuries"]
    assert f.current_value == "Three people injured (one critical)"
    assert len(f.history) == 1 and f.history[0].updated_by == "Operator-Lead"

    print(">>> 5. Disconnect is an event, not an end...")
    inc = orchestrator.handle_caller_disconnection(inc.incident_id, "Premature cell tower drop")
    assert inc.connection_state == ConnectionState.DISCONNECTED
    assert inc.state == IncidentState.OPERATOR_REVIEW

    print(">>> 6. Restart: a fresh engine reads the same incident back from disk...")
    restored = PersistenceEngine(os.environ["RESQ_DB_PATH"]).get_incident(inc.incident_id)
    assert restored is not None
    assert restored.fields["reported_injuries"].current_value == "Three people injured (one critical)"
    assert restored.connection_state == ConnectionState.DISCONNECTED



def test_guards():
    print(">>> 7. Dispatch needs approval; no double approval; no going backwards...")
    inc = orchestrator.create_incident("Fire Hazard", "en")
    fire = coordination_agent.create_action_proposal(inc, "NOTIFY_FIRE_RESCUE", "Fire 101")
    assert inc.state == IncidentState.ESCALATION_PENDING
    assert_raises(Conflict, orchestrator.record_agency_acknowledgment, inc.incident_id, fire.action_id)
    asyncio.run(orchestrator.approve_and_dispatch(inc.incident_id, fire.action_id, "Op"))
    assert_raises(Conflict, orchestrator.operator_approve_action, inc.incident_id, fire.action_id, "Op")
    orchestrator.record_agency_acknowledgment(inc.incident_id, fire.action_id, "FIRE-1")
    ems = coordination_agent.create_action_proposal(inc, "DISPATCH_EMS", "Ambulance 108")
    asyncio.run(orchestrator.approve_and_dispatch(inc.incident_id, ems.action_id, "Op"))
    assert orchestrator.get_incident(inc.incident_id).state == IncidentState.ACKNOWLEDGED

    print(">>> 8. Closed incidents can't dispatch; unknown IDs are NotFound...")
    closed = orchestrator.create_incident()
    late = coordination_agent.create_action_proposal(closed, "DISPATCH_EMS", "Ambulance 108")
    closed.state = IncidentState.CLOSED  # no close endpoint yet
    assert_raises(Conflict, orchestrator.operator_approve_action, closed.incident_id, late.action_id, "Op")
    assert_raises(Conflict, coordination_agent.create_action_proposal, closed, "DISPATCH_EMS", "Ambulance 108")
    assert_raises(NotFound, orchestrator.get_incident, "NOPE")

    print(">>> 9. API returns 404/409 and reads operator_id from the body...")
    c = TestClient(app)
    assert c.post("/api/incidents/NOPE/disconnect", json={}).status_code == 404
    inc2 = orchestrator.create_incident()
    a2 = coordination_agent.create_action_proposal(inc2, "DISPATCH_EMS", "Ambulance 108")
    assert c.post(f"/api/incidents/{inc2.incident_id}/simulate-ack", json={"action_id": a2.action_id}).status_code == 409
    assert c.post(f"/api/incidents/{inc2.incident_id}/acknowledge", json={"operator_id": "Operator-Lead"}).json()["assigned_operator"] == "Operator-Lead"


def test_gemini_path():
    """Offline: Gemini is faked, so this checks our mapping and failure handling, not the model."""
    real = voice_agent_module.extract_incident_data
    fake = Extraction(
        category="Road Accident", injuries="two people bleeding", affected_count=2, hazards=[],
        incident_location_text="Gemini flyover", caller_location_text="on a bus", caller_on_scene=False,
        urgency="HIGH", missing=["exact location"], next_question_en="Which side of the flyover?",
        next_question_ta="மேம்பாலத்தின் எந்தப் பக்கம்?", confidence=0.8,
    )

    async def fake_extract(_):
        return fake

    async def failing_extract(_):
        raise TimeoutError()

    try:
        print(">>> 10. Gemini path: fields mapped, no fake pin, Tamil follow-up, operator value survives re-extraction...")
        voice_agent_module.extract_incident_data = fake_extract
        inc = orchestrator.create_incident("Road Accident", "ta")
        inc = asyncio.run(voice_agent.process_utterance(inc, "Gemini flyover kitta accident, naan bus la irukken", "ta"))
        assert inc.fields["affected_count"].current_value == 2
        assert inc.fields["reported_injuries"].verification_status == VerificationStatus.AI_INFERRED_AWAITING_CONFIRMATION
        loc = inc.locations.incident_location
        assert loc.description == "Gemini flyover" and loc.latitude is None
        assert loc.verification_status == VerificationStatus.UNCERTAIN
        assert inc.locations.is_separated and inc.locations.caller_location.description == "on a bus"
        assert inc.follow_up_queue[0].question_text == "மேம்பாலத்தின் எந்தப் பக்கம்?"
        orchestrator.operator_override_field(inc.incident_id, "affected_count", 3, "Seen on CCTV", "Op")
        inc = asyncio.run(voice_agent.process_utterance(inc, "please hurry", "ta"))
        assert inc.fields["affected_count"].current_value == 3

        print(">>> 11. Gemini failure: flagged for review, keyword fallback, follow-up keeps the category...")
        voice_agent_module.extract_incident_data = failing_extract
        inc2 = orchestrator.create_incident("Fire Hazard", "en")
        inc2 = asyncio.run(voice_agent.process_utterance(inc2, "Huge fire and smoke at the textile shop", "en"))
        assert inc2.state == IncidentState.OPERATOR_REVIEW
        assert any(e.event_type == "AI_SERVICE_FAILURE" for e in db_engine.get_events(inc2.incident_id))
        inc2 = asyncio.run(voice_agent.process_utterance(inc2, "I am calling from my office", "en"))
        assert inc2.category.value == "Fire Hazard"
    finally:
        voice_agent_module.extract_incident_data = real


def test_routing_and_dispatch():
    print(">>> 12. Routing table: every category has a row; injuries add an ambulance first...")
    C = IncidentCategory
    expect = {
        C.ROAD_ACCIDENT: ["ALERT_TRAFFIC_POLICE"],
        C.FIRE_HAZARD: ["NOTIFY_FIRE_RESCUE"],
        C.MEDICAL_EMERGENCY: ["DISPATCH_EMS"],
        C.INDUSTRIAL_LEAK: ["NOTIFY_FIRE_RESCUE", "DISPATCH_EMS"],
        C.STRUCTURAL_COLLAPSE: ["NOTIFY_FIRE_RESCUE", "DISPATCH_EMS"],
        C.CRIMINAL_VIOLENCE: ["ALERT_POLICE"],
        C.NATURAL_DISASTER: ["NOTIFY_FIRE_RESCUE"],
        C.OTHER: [],
    }
    assert set(expect) == set(C)
    for cat, action_types in expect.items():
        assert [t for t, _ in coordination_agent.route(IncidentRecord(category=cat))] == action_types, cat
    hurt = IncidentRecord(category=C.ROAD_ACCIDENT)
    hurt.fields["reported_injuries"] = FieldProvenance(field_name="reported_injuries", current_value="bleeding")
    assert [t for t, _ in coordination_agent.route(hurt)] == ["DISPATCH_EMS", "ALERT_TRAFFIC_POLICE"]

    print(">>> 13. Auto-propose once per department; no duplicate noise on later turns...")
    inc = orchestrator.create_incident("Fire Hazard", "en")
    inc.fields["reported_injuries"] = FieldProvenance(field_name="reported_injuries", current_value="burns")
    first = coordination_agent.auto_propose(inc)
    assert [a.action_type for a in first] == ["DISPATCH_EMS", "NOTIFY_FIRE_RESCUE"]
    assert coordination_agent.auto_propose(inc) == []
    assert not any(e.event_type == "DUPLICATE_PREVENTED" for e in db_engine.get_events(inc.incident_id))

    print(">>> 14. SENT only when delivered; FAILED is visible and retryable; message is templated...")
    ems, fire = first
    a = asyncio.run(orchestrator.approve_and_dispatch(inc.incident_id, ems.action_id, "Op"))
    assert a.status == ActionStatus.SENT and "Simulated" in a.delivery_note

    sent = []

    def fake_telegram(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

    os.environ["TELEGRAM_BOT_TOKEN"] = "test-token"
    try:
        a = asyncio.run(orchestrator.approve_and_dispatch(inc.incident_id, fire.action_id, "Op"))
        assert a.status == ActionStatus.FAILED and "TELEGRAM_CHAT_FIRE" in a.delivery_note
        assert any(e.event_type == "DISPATCH_FAILED" and e.is_failure_event for e in db_engine.get_events(inc.incident_id))

        os.environ["TELEGRAM_CHAT_FIRE"] = "-1001"
        dispatch_service.httpx = types.SimpleNamespace(
            AsyncClient=lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(fake_telegram), **kw)
        )
        a = asyncio.run(orchestrator.approve_and_dispatch(inc.incident_id, fire.action_id, "Op"))
        assert a.status == ActionStatus.SENT and a.retry_count == 1 and "message 42" in a.delivery_note
        assert sent[0]["chat_id"] == "-1001"
        assert "SIMULATION" in sent[0]["text"] and "Fire Hazard" in sent[0]["text"]
        assert "maps.google.com" not in sent[0]["text"]  # unconfirmed location gets no map link
    finally:
        dispatch_service.httpx = httpx
        os.environ["TELEGRAM_BOT_TOKEN"] = ""
        os.environ["TELEGRAM_CHAT_FIRE"] = ""


def test_location_confirmation_and_dropped_call():
    import backend.main as main_module
    real_extract = voice_agent_module.extract_incident_data
    real_find = main_module.find_candidates
    fake = Extraction(
        category="Road Accident", injuries="two bleeding", affected_count=2, hazards=[],
        incident_location_text="Gemini flyover kitta", location_search_query="Gemini Flyover, Chennai",
        caller_location_text=None, caller_on_scene=True, urgency="HIGH", missing=["exact location"],
        next_question_en="Which side?", next_question_ta="எந்தப் பக்கம்?", confidence=0.8,
    )

    async def fake_extract(_):
        return fake

    async def fake_find(query):
        return [{"lat": 13.0516, "lon": 80.2503, "name": f"Anna Flyover ({query})"}]

    try:
        voice_agent_module.extract_incident_data = fake_extract
        main_module.find_candidates = fake_find

        print(">>> 15. Dropped call: departments already proposed, incident goes to review, dispatch still possible...")
        inc = orchestrator.create_incident("Road Accident", "en")
        inc = asyncio.run(voice_agent.process_utterance(inc, "Gemini flyover kitta accident, two bleeding", "en"))
        coordination_agent.auto_propose(inc)
        inc = orchestrator.handle_caller_disconnection(inc.incident_id, "Call dropped")
        assert inc.state == IncidentState.OPERATOR_REVIEW
        assert sorted(a.action_type for a in inc.coordination_actions) == ["ALERT_TRAFFIC_POLICE", "DISPATCH_EMS"]
        ems = next(a for a in inc.coordination_actions if a.action_type == "DISPATCH_EMS")
        assert asyncio.run(orchestrator.approve_and_dispatch(inc.incident_id, ems.action_id, "Op")).status == ActionStatus.SENT

        print(">>> 16. Location: candidates only; operator confirms; pin + map link; never overwritten...")
        c = TestClient(app)
        cands = c.get(f"/api/incidents/{inc.incident_id}/location-candidates").json()
        assert cands and "Gemini Flyover, Chennai" in cands[0]["name"]  # clean query from Gemini is tried first
        assert orchestrator.get_incident(inc.incident_id).locations.incident_location.latitude is None  # search alone pins nothing
        assert c.post(f"/api/incidents/{inc.incident_id}/confirm-location", json={"lat": 200, "lon": 80}).status_code == 422
        r = c.post(f"/api/incidents/{inc.incident_id}/confirm-location", json={"lat": 13.0516, "lon": 80.2503, "label": "Anna Flyover", "operator_id": "Op"})
        loc = r.json()["locations"]["incident_location"]
        assert loc["verification_status"] == "INDEPENDENTLY_VERIFIED" and loc["latitude"] == 13.0516
        inc = orchestrator.get_incident(inc.incident_id)
        traffic = next(a for a in inc.coordination_actions if a.action_type == "ALERT_TRAFFIC_POLICE")
        assert "maps.google.com/?q=13.0516,80.2503" in dispatch_service.format_message(inc, traffic)
        inc = asyncio.run(voice_agent.process_utterance(inc, "please hurry", "en"))
        assert inc.locations.incident_location.latitude == 13.0516  # AI re-extraction keeps the confirmed pin
        voice_agent_module.extract_incident_data = real_extract  # keyword path (no key) must keep it too
        inc = asyncio.run(voice_agent.process_utterance(inc, "it is near the bridge", "en"))
        assert inc.locations.incident_location.latitude == 13.0516

        missing = orchestrator.create_incident()
        assert c.get(f"/api/incidents/{missing.incident_id}/location-candidates").json() == []
    finally:
        voice_agent_module.extract_incident_data = real_extract
        main_module.find_candidates = real_find


def test_telegram_acknowledge_button():
    import backend.main as main_module
    print(">>> 17. Telegram Acknowledge tap -> agency ACK on the incident; button replaced; second tap refused...")
    inc = orchestrator.create_incident("Fire Hazard", "en")
    act = coordination_agent.create_action_proposal(inc, "NOTIFY_FIRE_RESCUE", "Fire & Rescue (101)")
    asyncio.run(orchestrator.approve_and_dispatch(inc.incident_id, act.action_id, "Op"))  # simulated delivery: no token in tests
    calls = []

    def fake_telegram(request):
        calls.append((request.url.path.rsplit("/", 1)[-1], json.loads(request.content)))
        return httpx.Response(200, json={"ok": True, "result": True})

    update = {"update_id": 1, "callback_query": {
        "id": "cb1", "from": {"first_name": "Ravi"}, "data": f"ack:{inc.incident_id}:{act.action_id}",
        "message": {"message_id": 7, "chat": {"id": -100}},
    }}

    async def tap_twice():
        async with httpx.AsyncClient(transport=httpx.MockTransport(fake_telegram)) as client:
            for _ in range(2):
                await dispatch_service.handle_update(client, "https://api.telegram.org/botX", update, main_module._on_telegram_ack)

    asyncio.run(tap_twice())
    a = orchestrator._find_action(orchestrator.get_incident(inc.incident_id), act.action_id)
    assert a.status == ActionStatus.ACKNOWLEDGED and "Ravi" in a.acknowledgment_reference
    assert orchestrator.get_incident(inc.incident_id).state == IncidentState.ACKNOWLEDGED
    assert [name for name, _ in calls] == ["editMessageReplyMarkup", "answerCallbackQuery", "answerCallbackQuery"]
    assert calls[1][1]["text"].startswith("Acknowledged") and calls[2][1]["text"].startswith("Not acknowledged")


def test_duplicate_callers():
    from datetime import datetime, timedelta
    from backend.agents.reasoning_agent import reasoning_agent
    from backend.models.incident import LocationRecord

    def reported(place_query, description, minutes_ago=0, category="Road Accident"):
        inc = orchestrator.create_incident(category, "en")
        inc.locations.incident_location = LocationRecord(
            description=description, search_query=place_query, verification_status=VerificationStatus.UNCERTAIN)
        inc.fields["reported_injuries"] = FieldProvenance(field_name="reported_injuries", current_value="hurt")
        inc.created_at = (datetime.utcnow() - timedelta(minutes=minutes_ago)).isoformat()
        db_engine.save_incident(inc)
        return inc

    print(">>> 18. Duplicate callers: same place + within 15 min is flagged; other places or old reports are not...")
    first = reported("Gemini Flyover, Chennai", "Gemini flyover kitta")
    other_place = reported("Anna Nagar Tower Park, Chennai", "Anna Nagar tower park")
    old_same_place = reported("Gemini Flyover, Chennai", "Gemini flyover", minutes_ago=40)
    second = reported("Gemini Flyover, Chennai", "Gemini flyover signal, near the US consulate")
    second = reasoning_agent.evaluate_incident(second)
    flagged = [c["incident_id"] for c in second.reasoning.related_incident_candidates]
    assert first.incident_id in flagged
    assert other_place.incident_id not in flagged and old_same_place.incident_id not in flagged

    print(">>> 19. Merge: duplicate's pending dispatches cancelled; it can't dispatch again; report kept on target...")
    coordination_agent.auto_propose(second)
    assert len(second.coordination_actions) == 2
    c = TestClient(app)
    assert c.post(f"/api/incidents/{second.incident_id}/merge-into", json={"target_id": second.incident_id}).status_code == 409
    r = c.post(f"/api/incidents/{second.incident_id}/merge-into", json={"target_id": first.incident_id, "operator_id": "Op"})
    assert r.status_code == 200 and r.json()["is_merged"] and r.json()["merged_into_id"] == first.incident_id
    second = orchestrator.get_incident(second.incident_id)
    assert all(a.status == ActionStatus.CANCELLED for a in second.coordination_actions)
    assert_raises(Conflict, orchestrator.operator_approve_action, second.incident_id, second.coordination_actions[0].action_id, "Op")
    assert coordination_agent.auto_propose(second) == []
    assert any(second.incident_id in n for n in orchestrator.get_incident(first.incident_id).operator_notes)
    still_flagged = [c["incident_id"] for c in reasoning_agent.evaluate_incident(first).reasoning.related_incident_candidates]
    assert second.incident_id not in still_flagged  # merged reports drop out of the candidate list


def test_caller_screen_and_device_location():
    print(">>> 20. Caller screen served; device GPS stored as caller location and not overwritten by words...")
    c = TestClient(app)
    assert c.get("/caller").status_code == 200 and "Call 112" in c.get("/caller").text
    inc = orchestrator.create_incident("Other Emergency", "en")
    assert c.post(f"/api/incidents/{inc.incident_id}/caller-location", json={"lat": 13.04, "lon": 80.23, "accuracy_m": -5}).status_code == 422
    r = c.post(f"/api/incidents/{inc.incident_id}/caller-location", json={"lat": 13.04, "lon": 80.23, "accuracy_m": 25})
    assert r.status_code == 200 and r.json()["locations"]["caller_location"]["source"] == "DEVICE_GPS"
    inc = asyncio.run(voice_agent.process_utterance(inc, "Accident near the bridge, I am calling from my office", "en"))
    caller = inc.locations.caller_location
    assert caller.latitude == 13.04 and caller.source.value == "DEVICE_GPS"
    assert inc.locations.is_separated  # words still tell us the caller is away from the scene


def test_conversation_suggested_pin_and_pre_alert():
    import backend.main as main_module
    real_extract, real_find = voice_agent_module.extract_incident_data, main_module.find_candidates
    seen_prompts, find_calls = [], []
    fake = Extraction(
        category="Road Accident", injuries="two bleeding", affected_count=2, hazards=[],
        incident_location_text="Gemini flyover kitta", location_search_query="Gemini Flyover, Chennai",
        caller_on_scene=False, caller_location_text="bus", urgency="HIGH", missing=["exact spot"],
        next_question_en="Which side of the flyover?", next_question_ta="மேம்பாலத்தின் எந்தப் பக்கம்?", confidence=0.8,
    )

    async def fake_extract(conversation):
        seen_prompts.append(conversation)
        return fake

    async def fake_find(query, limit=3):
        find_calls.append(query)
        if query == "US Consulate":
            return [{"lat": 13.0525, "lon": 80.2511, "name": "US Consulate"}]
        if "unmappable" in query or "Consulate" in query or "service road" in query:
            return []
        return [{"lat": 13.0516, "lon": 80.2503, "name": "Anna Flyover"}]

    sent = []

    def fake_telegram(request):
        body = json.loads(request.content)
        sent.append(body)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 100 + len(sent)}})

    real_spawn = main_module._spawn
    background = []
    try:
        voice_agent_module.extract_incident_data, main_module.find_candidates = fake_extract, fake_find
        main_module._spawn = background.append  # run the after-reply work ourselves, deterministically
        main_module.NOMINATIM_GAP_S = 0
        c = TestClient(app)

        def say(iid, text):
            c.post(f"/api/incidents/{iid}/voice-intake", json={"transcript": text, "language": "ta"})
            while background:
                asyncio.run(background.pop(0))

        print(">>> 21. Conversation stored turn by turn; Gemini sees the questions it already asked...")
        iid = c.post("/api/incidents", json={"category": "Other Emergency", "language": "ta"}).json()["incident_id"]
        say(iid, "Gemini flyover kitta accident")
        say(iid, "US consulate opposite side")
        turns = c.get(f"/api/incidents/{iid}/conversation").json()
        assert [t["speaker"] for t in turns] == ["caller", "resq", "caller", "resq"]
        assert turns[1]["text"] == "மேம்பாலத்தின் எந்தப் பக்கம்?"
        assert "RESQ asked: மேம்பாலத்தின் எந்தப் பக்கம்?" in seen_prompts[-1] and "Caller: US consulate opposite side" in seen_prompts[-1]

        print(">>> 22. Suggested pin: looked up after the reply, shown as UNCERTAIN, not re-searched for the same place...")
        loc = orchestrator.get_incident(iid).locations.incident_location
        assert loc.latitude == 13.0516 and loc.verification_status == VerificationStatus.UNCERTAIN and "Suggested" in loc.precision
        assert find_calls == ["Gemini Flyover, Chennai"]  # second turn kept the suggestion
        fake.location_search_query = "US Consulate, Gemini Flyover, Chennai"  # more detail: exact search fails, a part matches
        say(iid, "near the US consulate")
        assert find_calls[-2:] == ["US Consulate, Gemini Flyover, Chennai", "US Consulate"]
        assert orchestrator.get_incident(iid).locations.incident_location.latitude == 13.0525
        fake.location_search_query = "Gemini flyover service road"  # refinement with no match at all: keep the pin
        say(iid, "on the service road")
        assert orchestrator.get_incident(iid).locations.incident_location.latitude == 13.0525
        fake.location_search_query = "Some unmappable place"  # caller corrects the place; no map match
        say(iid, "sorry, it is somewhere else")
        assert find_calls[-1] == "Some unmappable place"
        assert orchestrator.get_incident(iid).locations.incident_location.latitude is None  # old pin cleared, not left wrong
        fake.location_search_query = "Gemini Flyover, Chennai"
        say(iid, "no wait, it is Gemini flyover after all")
        assert orchestrator.get_incident(iid).locations.incident_location.latitude == 13.0516  # pin back for the right place
        inc = orchestrator.get_incident(iid)
        ems = next(a for a in inc.coordination_actions if a.action_type == "DISPATCH_EMS")
        text = dispatch_service.format_message(inc, ems)
        assert "SUGGESTED by map search, NOT confirmed" in text and "maps.google.com/?q=13.0516,80.2503" in text

        print(">>> 23. Pre-alert goes out on routing (no button, still CREATED); confirmed dispatch replies to it with Acknowledge...")
        inc2 = orchestrator.create_incident("Fire Hazard", "en")
        fire = coordination_agent.create_action_proposal(inc2, "NOTIFY_FIRE_RESCUE", "Fire & Rescue (101)")
        os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_FIRE"] = "test-token", "-1001"
        dispatch_service.httpx = types.SimpleNamespace(
            AsyncClient=lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(fake_telegram), **kw))
        a = asyncio.run(orchestrator.pre_alert(inc2.incident_id, fire.action_id))
        assert a.status == ActionStatus.CREATED and a.pre_alert_message_id == 101 and "Pre-alert delivered" in a.pre_alert_note
        assert "PRE-ALERT" in sent[0]["text"] and "reply_markup" not in sent[0]
        assert asyncio.run(orchestrator.pre_alert(inc2.incident_id, fire.action_id)).pre_alert_message_id == 101  # not sent twice
        a = asyncio.run(orchestrator.approve_and_dispatch(inc2.incident_id, fire.action_id, "Op"))
        assert a.status == ActionStatus.SENT and "CONFIRMED DISPATCH" in sent[1]["text"]
        assert sent[1]["reply_parameters"]["message_id"] == 101 and "Acknowledge" in json.dumps(sent[1]["reply_markup"], ensure_ascii=False)

        print(">>> 24. Merging a pre-alerted duplicate tells the department it's cancelled...")
        first = orchestrator.create_incident("Fire Hazard", "en")
        dup = orchestrator.create_incident("Fire Hazard", "en")
        dup_fire = coordination_agent.create_action_proposal(dup, "NOTIFY_FIRE_RESCUE", "Fire & Rescue (101)")
        dup_alert = asyncio.run(orchestrator.pre_alert(dup.incident_id, dup_fire.action_id))
        assert c.post(f"/api/incidents/{dup.incident_id}/merge-into", json={"target_id": first.incident_id}).status_code == 200
        assert sent[-1]["text"].startswith("CANCELLED")
        assert sent[-1]["reply_parameters"]["message_id"] == dup_alert.pre_alert_message_id
    finally:
        voice_agent_module.extract_incident_data, main_module.find_candidates = real_extract, real_find
        main_module._spawn = real_spawn
        main_module.NOMINATIM_GAP_S = 1.1
        dispatch_service.httpx = httpx
        os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_FIRE"] = "", ""


def test_lyzr_brief_and_band_feed():
    import backend.services.lyzr_service as lyzr
    from backend.services import band_service
    print(">>> 25. Lyzr crew brief after dispatch (and when Lyzr fails); BAND feed lines and @RESQ answers...")
    inc = orchestrator.create_incident("Fire Hazard", "en")
    db_engine.add_turn(inc.incident_id, "caller", "Fire in the godown near the market")
    act = coordination_agent.create_action_proposal(inc, "NOTIFY_FIRE_RESCUE", "Fire & Rescue (101)")
    asyncio.run(orchestrator.approve_and_dispatch(inc.incident_id, act.action_id, "Op"))
    assert asyncio.run(orchestrator.send_handover_brief(inc.incident_id, act.action_id)) is False  # no keys: no call, no event

    calls, chats, status = [], [], [200]

    def fake_lyzr(request):
        calls.append(f"{request.method} {request.url.path}")
        if request.url.path == "/v3/agents/":  # only the API key is configured: find our agent, else create it
            return httpx.Response(200, json={"agents": [{"id": "other", "name": "Finance Advisor"}]} if request.method == "GET" else {"agent_id": "new1"})
        chats.append(json.loads(request.content))
        return httpx.Response(status[0], json={"response": "Fire at a godown near the market (caller's words). Verify the address first."})

    os.environ["LYZR_API_KEY"] = "k"
    lyzr.httpx = types.SimpleNamespace(AsyncClient=lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(fake_lyzr), **kw))
    try:
        assert asyncio.run(orchestrator.send_handover_brief(inc.incident_id, act.action_id)) is True
        assert calls == ["GET /v3/agents/", "POST /v3/agents/", "POST /v3/inference/chat/"]
        assert chats[0]["agent_id"] == "new1" and chats[0]["session_id"].endswith(inc.incident_id)
        assert "Caller: Fire in the godown" in chats[0]["message"] and "To: Fire & Rescue" in chats[0]["message"]
        status[0] = 500
        assert asyncio.run(orchestrator.send_handover_brief(inc.incident_id, act.action_id)) is False
        assert calls[3:] == ["POST /v3/inference/chat/"]  # the agent id is cached, not looked up again
    finally:
        lyzr.httpx, lyzr._agent_id = httpx, None
        os.environ["LYZR_API_KEY"] = ""
    events = {e.event_type: e for e in db_engine.get_events(inc.incident_id)}
    assert "godown" in events["HANDOVER_BRIEF"].summary
    assert events["HANDOVER_BRIEF_FAILED"].is_failure_event and "HTTPStatusError" in events["HANDOVER_BRIEF_FAILED"].summary

    # Timeline listeners (the BAND feed) see every stored event, and a broken one can't stop the record
    got = []
    db_engine.listeners[:] = [lambda e: 1 / 0, got.append]
    try:
        orchestrator.operator_acknowledge(inc.incident_id, "Op")
    finally:
        db_engine.listeners.clear()
    assert got and got[-1].event_type == "OPERATOR_ACKNOWLEDGED"
    assert any(e.event_type == "OPERATOR_ACKNOWLEDGED" for e in db_engine.get_events(inc.incident_id))

    suffix = inc.incident_id[-6:]
    assert band_service.feed_line(events["HANDOVER_BRIEF"]).startswith(f"[Lyzr Handover Agent] {suffix}: ")
    assert band_service.feed_line(events["HANDOVER_BRIEF_FAILED"]).startswith("⚠ ")
    incidents = db_engine.list_incidents()
    assert band_service.answer(f"@RESQ what about {suffix.lower()}?", incidents).startswith(inc.incident_id)
    listing = band_service.answer("@RESQ status", incidents)
    assert listing.startswith("Open incidents") and suffix in listing


if __name__ == "__main__":
    test_full_pipeline()
    test_guards()
    test_gemini_path()
    test_routing_and_dispatch()
    test_location_confirmation_and_dropped_call()
    test_telegram_acknowledge_button()
    test_duplicate_callers()
    test_caller_screen_and_device_location()
    test_conversation_suggested_pin_and_pre_alert()
    test_lyzr_brief_and_band_feed()
    print("ALL CHECKS PASSED")
