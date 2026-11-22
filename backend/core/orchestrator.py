"""
RESQ 4.0 Central Orchestration & Safety Engine
The authoritative controller enforcing state transitions, authorization policies,
safety constraints, failure continuity, and human-in-the-loop governance.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime

from backend.models.incident import (
    IncidentRecord,
    TimelineEvent,
    FieldProvenance,
    ProvenanceHistory,
    CoordinationAction,
    LocationRecord
)
from backend.models.enums import (
    IncidentState,
    VerificationStatus,
    ProvenanceSource,
    ActionStatus,
    ConnectionState,
    IncidentCategory
)
from backend.core.persistence import db_engine
from backend.services import dispatch_service

class NotFound(Exception):
    """Maps to HTTP 404."""

class Conflict(Exception):
    """Maps to HTTP 409: the request is illegal in the current state."""

CLOSED_STATES = (IncidentState.RESOLUTION_REVIEW, IncidentState.CLOSED)

# Valid allowed state transitions
VALID_TRANSITIONS: Dict[IncidentState, List[IncidentState]] = {
    IncidentState.RECEIVED: [IncidentState.INFORMATION_GATHERING, IncidentState.OPERATOR_REVIEW, IncidentState.ESCALATION_PENDING],
    IncidentState.INFORMATION_GATHERING: [IncidentState.VALIDATION, IncidentState.OPERATOR_REVIEW, IncidentState.ESCALATION_PENDING],
    IncidentState.VALIDATION: [IncidentState.OPERATOR_REVIEW, IncidentState.ESCALATION_PENDING],
    IncidentState.OPERATOR_REVIEW: [IncidentState.ESCALATION_PENDING, IncidentState.ESCALATION_SENT, IncidentState.RESOLUTION_REVIEW, IncidentState.CLOSED],
    IncidentState.ESCALATION_PENDING: [IncidentState.ESCALATION_SENT, IncidentState.OPERATOR_REVIEW],
    IncidentState.ESCALATION_SENT: [IncidentState.ACKNOWLEDGED, IncidentState.OPERATOR_REVIEW],
    IncidentState.ACKNOWLEDGED: [IncidentState.ASSIGNED, IncidentState.ACTIVE_MONITORING],
    IncidentState.ASSIGNED: [IncidentState.ACTIVE_MONITORING, IncidentState.RESOLUTION_REVIEW],
    IncidentState.ACTIVE_MONITORING: [IncidentState.RESOLUTION_REVIEW, IncidentState.OPERATOR_REVIEW],
    IncidentState.RESOLUTION_REVIEW: [IncidentState.CLOSED, IncidentState.ACTIVE_MONITORING],
    IncidentState.CLOSED: [IncidentState.OPERATOR_REVIEW] # Allow reopening
}

class OrchestrationEngine:
    def create_incident(self, category_str: str = "Road Accident", language: str = "en") -> IncidentRecord:
        matched_category = IncidentCategory.ROAD_ACCIDENT
        for cat in IncidentCategory:
            if cat.value.lower() == category_str.lower() or cat.name.lower() == category_str.lower():
                matched_category = cat
                break
        incident = IncidentRecord(category=matched_category, language=language)
        incident = db_engine.save_incident(incident)
        
        evt = TimelineEvent(
            incident_id=incident.incident_id,
            event_type="INTAKE_INITIATED",
            actor="Central Orchestration Engine",
            summary=f"New emergency incident initialized with ID: {incident.incident_id}",
            details={"language": language, "initial_state": incident.state.value}
        )
        db_engine.log_event(evt)
        return incident

    def get_incident(self, incident_id: str) -> IncidentRecord:
        incident = db_engine.get_incident(incident_id)
        if not incident:
            raise NotFound(f"Incident {incident_id} not found")
        return incident

    def can_advance(self, incident: IncidentRecord, new_state: IncidentState) -> bool:
        return new_state in VALID_TRANSITIONS.get(incident.state, [])

    def advance(self, incident: IncidentRecord, new_state: IncidentState, actor: str, reason: str) -> None:
        """The only place incident.state changes. Logs the change; the caller saves the incident."""
        if incident.state == new_state:
            return
        if not self.can_advance(incident, new_state):
            raise Conflict(f"Illegal state transition {incident.state.value} -> {new_state.value}")
        old = incident.state
        incident.state = new_state
        db_engine.log_event(TimelineEvent(
            incident_id=incident.incident_id,
            event_type="STATE_CHANGE",
            actor=actor,
            summary=f"State {old.value} -> {new_state.value}: {reason}",
            details={"from_state": old.value, "to_state": new_state.value, "reason": reason}
        ))

    def handle_caller_disconnection(self, incident_id: str, reason: str = "Abrupt line termination detected") -> IncidentRecord:
        """
        Core Innovation: A communication failure is an incident event, NEVER an incident termination.
        Persists available data, marks interruption, alerts human operator.
        """
        incident = self.get_incident(incident_id)
        
        incident.connection_state = ConnectionState.DISCONNECTED
        
        # Check if incident location is still uncertain or missing
        if incident.locations.incident_location.verification_status in [VerificationStatus.MISSING, VerificationStatus.UNCERTAIN]:
            incident.reasoning.missing_critical_fields.append("Exact Incident Location (Call Interrupted)")
            
        incident.reasoning.operator_action_recommendations.append("URGENT: Caller disconnected prematurely. Operator review and cross-referencing required.")
        
        # Safely transition to OPERATOR_REVIEW so human operator has immediate review control
        if incident.state in [IncidentState.RECEIVED, IncidentState.INFORMATION_GATHERING, IncidentState.VALIDATION, IncidentState.ESCALATION_PENDING]:
            self.advance(incident, IncidentState.OPERATOR_REVIEW, "Continuity Engine (Disconnection Handler)", reason)
            
        db_engine.save_incident(incident)
        
        evt = TimelineEvent(
            incident_id=incident_id,
            event_type="COMMUNICATION_INTERRUPTION",
            actor="Continuity Engine (Disconnection Handler)",
            summary="Caller disconnected. State persisted; incomplete intake flagged for Operator Review.",
            details={"reason": reason, "missing_fields": incident.reasoning.missing_critical_fields},
            is_failure_event=True
        )
        db_engine.log_event(evt)
        return incident

    def handle_ai_service_failure(self, incident: IncidentRecord, agent_name: str, error_msg: str) -> IncidentRecord:
        """
        Gracefully absorbs AI timeouts or crashes without terminating incident.
        Takes the caller's incident object so it can't save over in-flight changes with a stale copy.
        """
        error_msg = error_msg[:300]
        incident.reasoning.uncertain_fields.append(f"AI Service Failure ({agent_name})")
        incident.reasoning.operator_action_recommendations.append(f"Manual operator verification needed due to {agent_name} failure.")
        if self.can_advance(incident, IncidentState.OPERATOR_REVIEW):
            self.advance(incident, IncidentState.OPERATOR_REVIEW, "Continuity Engine (Agent Watchdog)", f"{agent_name} failed")
        db_engine.save_incident(incident)
        
        evt = TimelineEvent(
            incident_id=incident.incident_id,
            event_type="AI_SERVICE_FAILURE",
            actor="Continuity Engine (Agent Watchdog)",
            summary=f"{agent_name} encountered an error: {error_msg}. Preserving record and escalating to Operator.",
            details={"agent": agent_name, "error": error_msg},
            is_failure_event=True
        )
        db_engine.log_event(evt)
        return incident

    def operator_override_field(
        self,
        incident_id: str,
        field_name: str,
        new_value: Any,
        reason: str,
        operator_id: str = "Operator-1"
    ) -> IncidentRecord:
        """
        Allows human operator to correct or verify extracted information with full audit provenance.
        """
        incident = self.get_incident(incident_id)
        
        now = datetime.utcnow().isoformat()
        
        if field_name in incident.fields:
            existing = incident.fields[field_name]
            # Record in history
            existing.history.append(ProvenanceHistory(
                timestamp=now,
                previous_value=existing.current_value,
                updated_by=operator_id,
                reason=reason
            ))
            existing.current_value = new_value
            existing.source = ProvenanceSource.OPERATOR_OVERRIDE
            existing.verification_status = VerificationStatus.INDEPENDENTLY_VERIFIED
            existing.confidence = 1.0
        else:
            # New field entered by operator
            incident.fields[field_name] = FieldProvenance(
                field_name=field_name,
                current_value=new_value,
                original_value=None,
                source=ProvenanceSource.OPERATOR_OVERRIDE,
                timestamp=now,
                confidence=1.0,
                verification_status=VerificationStatus.INDEPENDENTLY_VERIFIED,
                extraction_method=f"Direct Operator Verification ({operator_id})"
            )
            
        incident.updated_at = now
        db_engine.save_incident(incident)
        
        evt = TimelineEvent(
            incident_id=incident_id,
            event_type="OPERATOR_FIELD_OVERRIDE",
            actor=operator_id,
            summary=f"Operator verified/overrode '{field_name}' to '{new_value}'",
            details={"field": field_name, "new_value": new_value, "reason": reason}
        )
        db_engine.log_event(evt)
        return incident

    def confirm_incident_location(self, incident_id: str, lat: float, lon: float, operator_id: str, label: Optional[str] = None) -> IncidentRecord:
        """The only way an incident gets a map pin: an operator confirms the point."""
        incident = self.get_incident(incident_id)
        old = incident.locations.incident_location
        incident.locations.incident_location = LocationRecord(
            description=old.description if old.verification_status != VerificationStatus.MISSING else (label or "Operator-placed pin"),
            latitude=lat,
            longitude=lon,
            source=ProvenanceSource.OPERATOR_OVERRIDE,
            timestamp=datetime.utcnow().isoformat(),
            precision="Operator-confirmed pin",
            verification_status=VerificationStatus.INDEPENDENTLY_VERIFIED,
            confidence=1.0,
            notes=f"Confirmed by {operator_id}" + (f" as {label}" if label else ""),
            search_query=old.search_query,
        )
        db_engine.save_incident(incident)
        db_engine.log_event(TimelineEvent(
            incident_id=incident_id,
            event_type="OPERATOR_LOCATION_CONFIRMED",
            actor=operator_id,
            summary=f"Confirmed incident location at {lat:.5f}, {lon:.5f}" + (f" ({label})" if label else ""),
            details={"previous": old.description, "previous_status": old.verification_status.value, "lat": lat, "lon": lon}
        ))
        return incident

    def operator_acknowledge(self, incident_id: str, operator_id: str = "Operator-1") -> IncidentRecord:
        incident = self.get_incident(incident_id)
        
        incident.operator_acknowledged = True
        incident.assigned_operator = operator_id
        if incident.state in (IncidentState.RECEIVED, IncidentState.VALIDATION):
            self.advance(incident, IncidentState.OPERATOR_REVIEW, operator_id, "Operator acknowledged")
            
        db_engine.save_incident(incident)
        
        evt = TimelineEvent(
            incident_id=incident_id,
            event_type="OPERATOR_ACKNOWLEDGED",
            actor=operator_id,
            summary=f"Incident acknowledged and assigned to {operator_id}",
            details={"operator_id": operator_id}
        )
        db_engine.log_event(evt)
        return incident

    def _find_action(self, incident: IncidentRecord, action_id: str) -> CoordinationAction:
        for act in incident.coordination_actions:
            if act.action_id == action_id:
                return act
        raise NotFound(f"Action {action_id} not found on incident {incident.incident_id}")

    def operator_approve_action(self, incident_id: str, action_id: str, operator_id: str = "Operator-1") -> CoordinationAction:
        """
        Human authorization. Marks the action QUEUED; it only becomes SENT once delivery succeeds.
        A FAILED action can be approved again (retry).
        """
        incident = self.get_incident(incident_id)
        target_action = self._find_action(incident, action_id)
        if incident.state in CLOSED_STATES:
            raise Conflict(f"Incident {incident_id} is {incident.state.value}; cannot dispatch")
        if target_action.status not in (ActionStatus.CREATED, ActionStatus.FAILED):
            raise Conflict(f"Action {action_id} is already {target_action.status.value}")

        if target_action.status == ActionStatus.FAILED:
            target_action.retry_count += 1
        target_action.operator_approved = True
        target_action.operator_id = operator_id
        target_action.status = ActionStatus.QUEUED
        db_engine.save_incident(incident)
        db_engine.save_action(target_action)

        db_engine.log_event(TimelineEvent(
            incident_id=incident_id,
            event_type="COORDINATION_APPROVED",
            actor=operator_id,
            summary=f"Operator approved dispatch of '{target_action.action_type}' to '{target_action.target_agency}'",
            details={"action_id": target_action.action_id, "agency": target_action.target_agency, "attempt": target_action.retry_count + 1}
        ))
        return target_action

    def record_delivery(self, incident_id: str, action_id: str, delivered: bool, note: str) -> CoordinationAction:
        """The system never assumes a dispatch went out: SENT only on confirmed delivery, otherwise FAILED."""
        incident = self.get_incident(incident_id)
        act = self._find_action(incident, action_id)
        act.delivery_note = note
        if delivered:
            act.status = ActionStatus.SENT
            act.transmitted_at = datetime.utcnow().isoformat()
            # A second department's dispatch must not move the incident backwards
            if self.can_advance(incident, IncidentState.ESCALATION_SENT):
                self.advance(incident, IncidentState.ESCALATION_SENT, act.operator_id or "Operator", f"Dispatched {act.action_type}")
        else:
            act.status = ActionStatus.FAILED
            incident.reasoning.operator_action_recommendations.append(
                f"Dispatch to {act.target_agency} failed ({note}). Retry or call the department directly."
            )
        db_engine.save_incident(incident)
        db_engine.save_action(act)
        db_engine.log_event(TimelineEvent(
            incident_id=incident_id,
            event_type="DISPATCH_DELIVERED" if delivered else "DISPATCH_FAILED",
            actor="Dispatch Service",
            summary=f"{act.target_agency}: {note}",
            details={"action_id": act.action_id, "delivered": delivered},
            is_failure_event=not delivered
        ))
        return act

    async def approve_and_dispatch(self, incident_id: str, action_id: str, operator_id: str = "Operator-1") -> CoordinationAction:
        action = self.operator_approve_action(incident_id, action_id, operator_id)
        delivered, note = await dispatch_service.deliver(self.get_incident(incident_id), action)
        return self.record_delivery(incident_id, action_id, delivered, note)

    def record_agency_acknowledgment(self, incident_id: str, action_id: str, responder_ref: str = "DISPATCH-UNIT-704") -> CoordinationAction:
        """
        Simulates agency response lifecycle: SENT -> ACKNOWLEDGED -> ASSIGNED
        """
        incident = self.get_incident(incident_id)
        
        for act in incident.coordination_actions:
            if act.action_id == action_id:
                if not act.operator_approved or act.status != ActionStatus.SENT:
                    raise Conflict(f"Action {action_id} must be operator-approved and SENT before an agency can acknowledge it (status: {act.status.value})")
                now = datetime.utcnow().isoformat()
                act.status = ActionStatus.ACKNOWLEDGED
                act.acknowledged_at = now
                act.acknowledgment_reference = responder_ref

                if self.can_advance(incident, IncidentState.ACKNOWLEDGED):
                    self.advance(incident, IncidentState.ACKNOWLEDGED, act.target_agency, f"ACK ref {responder_ref}")
                db_engine.save_incident(incident)
                db_engine.save_action(act)
                
                evt = TimelineEvent(
                    incident_id=incident_id,
                    event_type="AGENCY_ACKNOWLEDGED",
                    actor=act.target_agency,
                    summary=f"Agency '{act.target_agency}' acknowledged dispatch with ref: {responder_ref}",
                    details={"action_id": action_id, "ref": responder_ref}
                )
                db_engine.log_event(evt)
                return act
                
        raise NotFound(f"Action {action_id} not found on incident {incident_id}")

orchestrator = OrchestrationEngine()
