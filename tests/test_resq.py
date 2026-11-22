"""
RESQ 4.0 smoke test: intake -> reasoning -> idempotent proposal -> override -> disconnect -> restart.
Runs against a throwaway DB so the demo DB stays clean.
"""
import sys
import os
import tempfile

# Must be set before backend modules are imported (persistence reads it at import time)
os.environ["RESQ_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ.pop("GEMINI_API_KEY", None)  # keyword path only, so results are deterministic
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.core.orchestrator import orchestrator
from backend.agents.voice_agent import voice_agent
from backend.agents.reasoning_agent import reasoning_agent
from backend.agents.coordination_agent import coordination_agent
from backend.core.persistence import PersistenceEngine
from backend.models.enums import IncidentState, VerificationStatus, ConnectionState


def test_full_pipeline():
    print(">>> 1. Intake (Tamil, remote caller)...")
    inc = orchestrator.create_incident("Road Accident", "ta")
    assert inc.state == IncidentState.RECEIVED
    utterance = "வணக்கம், அண்ணா மேம்பாலம் அருகே ஒரு பெரிய விபத்து. இரண்டு பேர் பலத்த காயமடைந்துள்ளனர். நான் இங்க இல்ல, என் அலுவலகத்திலிருந்து பார்க்கிறேன்."
    inc = voice_agent.process_utterance(inc, utterance, "ta")
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

    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    test_full_pipeline()
