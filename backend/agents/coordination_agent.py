"""
RESQ 4.0 Coordination Agent (Agent 3)
Formulates emergency coordination proposals according to agency workflow rules,
tracks granular transmission and acknowledgment states, and enforces idempotency
controls to prevent duplicate dispatch requests.
"""
from typing import List, Dict, Any, Optional

from backend.models.incident import IncidentRecord, CoordinationAction
from backend.models.enums import IncidentCategory, IncidentState
from backend.core.persistence import db_engine
from backend.core.idempotency import idempotency_mgr

class CoordinationAgent:
    def recommend_actions(self, incident: IncidentRecord) -> List[Dict[str, Any]]:
        """
        Generates agency dispatch recommendations based on validated incident facts.
        """
        proposals = []
        
        # 1. Emergency Medical Team recommendation
        if "reported_injuries" in incident.fields or incident.category == IncidentCategory.MEDICAL_EMERGENCY:
            proposals.append({
                "action_type": "DISPATCH_EMS",
                "target_agency": "Emergency Medical Services (108)",
                "priority": "HIGH",
                "recommended_units": "Advanced Life Support (ALS) Ambulance",
                "reason": "Human casualties/injuries reported in intake"
            })
            
        # 2. Traffic Police recommendation
        if incident.category == IncidentCategory.ROAD_ACCIDENT:
            proposals.append({
                "action_type": "ALERT_TRAFFIC_POLICE",
                "target_agency": "City Traffic Control & Patrol",
                "priority": "MEDIUM",
                "recommended_units": "Sector Patrol Interceptor",
                "reason": "Road accident may obstruct key transit routes"
            })
            
        # 3. Fire Rescue recommendation
        if incident.category == IncidentCategory.FIRE_HAZARD or "immediate_danger" in incident.fields:
            proposals.append({
                "action_type": "NOTIFY_FIRE_RESCUE",
                "target_agency": "Fire & Rescue Department",
                "priority": "HIGH",
                "recommended_units": "Rapid Response Water Tender",
                "reason": "Active fire / structural or chemical risk detected"
            })
            
        return proposals

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
            # Advance incident state to ESCALATION_PENDING if currently in OPERATOR_REVIEW or VALIDATION
            if incident.state in [IncidentState.VALIDATION, IncidentState.OPERATOR_REVIEW]:
                incident.state = IncidentState.ESCALATION_PENDING
            db_engine.save_incident(incident)
            
        return action

coordination_agent = CoordinationAgent()
