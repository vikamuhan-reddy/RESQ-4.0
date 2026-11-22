"""
RESQ 4.0 Coordination Agent (Agent 3)
Formulates emergency coordination proposals according to agency workflow rules,
tracks granular transmission and acknowledgment states, and enforces idempotency
controls to prevent duplicate dispatch requests.
"""
from typing import List, Dict, Any, Optional, Tuple

from backend.models.incident import IncidentRecord, CoordinationAction
from backend.models.enums import IncidentCategory, IncidentState
from backend.core.persistence import db_engine
from backend.core.idempotency import idempotency_mgr
from backend.core.orchestrator import orchestrator, Conflict, CLOSED_STATES

AMBULANCE = ("DISPATCH_EMS", "Ambulance (108)")
FIRE = ("NOTIFY_FIRE_RESCUE", "Fire & Rescue (101)")
POLICE = ("ALERT_POLICE", "Police (100)")
TRAFFIC = ("ALERT_TRAFFIC_POLICE", "Traffic Police")

# Routing is rules, not AI: the model understands the call, this table decides who gets sent.
# An ambulance is added whenever injuries are reported. "Other" goes to the operator.
ROUTES: Dict[IncidentCategory, List[Tuple[str, str]]] = {
    IncidentCategory.ROAD_ACCIDENT: [TRAFFIC],
    IncidentCategory.FIRE_HAZARD: [FIRE],
    IncidentCategory.MEDICAL_EMERGENCY: [AMBULANCE],
    IncidentCategory.INDUSTRIAL_LEAK: [FIRE, AMBULANCE],
    IncidentCategory.STRUCTURAL_COLLAPSE: [FIRE, AMBULANCE],
    IncidentCategory.CRIMINAL_VIOLENCE: [POLICE],
    IncidentCategory.NATURAL_DISASTER: [FIRE],
    IncidentCategory.OTHER: [],
}


class CoordinationAgent:
    def route(self, incident: IncidentRecord) -> List[Tuple[str, str]]:
        """(action_type, agency) pairs for this incident, most urgent first."""
        departments = list(ROUTES.get(incident.category, []))
        if "reported_injuries" in incident.fields and AMBULANCE not in departments:
            departments.insert(0, AMBULANCE)
        return departments

    def auto_propose(self, incident: IncidentRecord) -> List[CoordinationAction]:
        """Proposes each routed department once per incident. Nothing is sent until an operator approves."""
        if incident.state in CLOSED_STATES or incident.is_merged:
            return []
        already = {a.action_type for a in incident.coordination_actions}
        return [
            self.create_action_proposal(incident, action_type, agency)
            for action_type, agency in self.route(incident)
            if action_type not in already
        ]

    def create_action_proposal(
        self,
        incident: IncidentRecord,
        action_type: str,
        target_agency: str,
        payload: Optional[Dict[str, Any]] = None,
        custom_idempotency_key: Optional[str] = None
    ) -> CoordinationAction:
        """
        Creates a proposed coordination action with idempotency enforcement.
        Note: The action remains in CREATED status until authorized by an operator.
        """
        if incident.state in CLOSED_STATES:
            raise Conflict(f"Incident {incident.incident_id} is {incident.state.value}; cannot propose dispatch")
        if incident.is_merged:
            raise Conflict(f"Incident {incident.incident_id} was merged into {incident.merged_into_id}; dispatch from that incident")

        # Generate stable idempotency key if not provided
        idemp_key = custom_idempotency_key or f"IDEMP-{incident.incident_id}-{action_type}"
        
        action_payload = payload or {
            "incident_id": incident.incident_id,
            "category": incident.category.value,
            "incident_location": incident.locations.incident_location.description,
            "location_verification": incident.locations.incident_location.verification_status.value,
            "injuries": incident.fields.get("reported_injuries", {}).current_value if "reported_injuries" in incident.fields else "None reported"
        }
        
        action, is_dup, msg = idempotency_mgr.process_action(
            idempotency_key=idemp_key,
            incident_id=incident.incident_id,
            action_type=action_type,
            target_agency=target_agency,
            payload=action_payload,
            operator_approved=False
        )
        
        # If new action, attach to incident
        if not is_dup:
            incident.coordination_actions.append(action)
            # Never moves an already-escalated incident backwards
            if orchestrator.can_advance(incident, IncidentState.ESCALATION_PENDING):
                orchestrator.advance(incident, IncidentState.ESCALATION_PENDING, "Coordination Agent", f"Proposed {action_type}")
            db_engine.save_incident(incident)
            
        return action

coordination_agent = CoordinationAgent()
