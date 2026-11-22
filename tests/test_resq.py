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
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from backend.main import app
from backend.core.orchestrator import orchestrator, Conflict, NotFound
from backend.agents.voice_agent import voice_agent
from backend.agents.reasoning_agent import reasoning_agent
from backend.agents.coordination_agent import coordination_agent
from backend.core.persistence import PersistenceEngine, db_engine
from backend.models.enums import IncidentState, VerificationStatus, ConnectionState
from backend.services.gemini_service import Extraction
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
    assert_raises(Conflict, orchestrator.simulate_agency_acknowledgment, inc.incident_id, fire.action_id)
    orchestrator.operator_approve_action(inc.incident_id, fire.action_id, "Op")
    assert_raises(Conflict, orchestrator.operator_approve_action, inc.incident_id, fire.action_id, "Op")
    orchestrator.simulate_agency_acknowledgment(inc.incident_id, fire.action_id, "FIRE-1")
    ems = coordination_agent.create_action_proposal(inc, "DISPATCH_EMS", "Ambulance 108")
    orchestrator.operator_approve_action(inc.incident_id, ems.action_id, "Op")
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


if __name__ == "__main__":
    test_full_pipeline()
    test_guards()
    test_gemini_path()
    print("ALL CHECKS PASSED")
