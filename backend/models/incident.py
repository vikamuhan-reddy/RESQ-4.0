"""
RESQ 4.0 Incident Models & Structured Schemas
Implements Dual-Location records, Field Provenance tracking, Agent Reasoning schemas,
Timeline Events, and Idempotent Coordination Action structures.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field
import uuid

from backend.models.enums import (
    IncidentState,
    VerificationStatus,
    ProvenanceSource,
    ActionStatus,
    UrgencyLevel,
    ConnectionState,
    IncidentCategory
)

def generate_id(prefix: str = "INC") -> str:
    return f"{prefix}-{datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

class ProvenanceHistory(BaseModel):
    timestamp: str
    previous_value: Any
    updated_by: str
    reason: Optional[str] = None

class FieldProvenance(BaseModel):
    field_name: str
    current_value: Any
    original_value: Any = None
    source: ProvenanceSource = ProvenanceSource.CALLER_VOICE
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    confidence: float = 1.0  # 0.0 to 1.0
    verification_status: VerificationStatus = VerificationStatus.CALLER_REPORTED
    extraction_method: str = "Direct Voice Transcription"
    transcript_reference: Optional[str] = None
    history: List[ProvenanceHistory] = Field(default_factory=list)

class LocationRecord(BaseModel):
    description: str = "Unknown location"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    source: ProvenanceSource = ProvenanceSource.CALLER_VOICE
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    precision: str = "Approximate / Landmark"  # "Exact GPS", "Street Level", "Landmark", "City Level", "Unknown"
    verification_status: VerificationStatus = VerificationStatus.CALLER_REPORTED
    confidence: float = 0.5
    notes: Optional[str] = None
    search_query: Optional[str] = None  # clean place name for "Find on map"; never auto-pinned

class DualLocation(BaseModel):
    caller_location: LocationRecord
    incident_location: LocationRecord
    is_separated: bool = False
    separation_rationale: Optional[str] = None

class TimelineEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: f"EVT-{uuid.uuid4().hex[:8]}")
    incident_id: str
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    event_type: str  # STATE_CHANGE, INTERRUPTION, RECOVERY, OPERATOR_ACTION, AGENT_INFERENCE, COORDINATION
    actor: str       # "Voice Intelligence Agent", "Incident Reasoning Agent", "Operator", "Continuity Engine", etc.
    summary: str
    details: Dict[str, Any] = Field(default_factory=dict)
    is_failure_event: bool = False

class CoordinationAction(BaseModel):
    action_id: str = Field(default_factory=lambda: f"ACT-{uuid.uuid4().hex[:8]}")
    idempotency_key: str
    incident_id: str
    action_type: str  # "DISPATCH_EMS", "ALERT_TRAFFIC_POLICE", "NOTIFY_FIRE_RESCUE", "HAZMAT_CONTAINMENT"
    target_agency: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    status: ActionStatus = ActionStatus.CREATED
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    transmitted_at: Optional[str] = None
    acknowledged_at: Optional[str] = None
    assigned_at: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    operator_approved: bool = False
    operator_id: Optional[str] = None
    acknowledgment_reference: Optional[str] = None
    delivery_note: Optional[str] = None  # what happened when we tried to deliver it (shown to the operator)
    is_simulation: bool = True  # Always True until real dispatch integration is wired
    dispatch_mode: str = "simulation"  # "simulation" | "live"

class AgentReasoning(BaseModel):
    urgency_explanation: str = "Pending evaluation"
    urgency_level: UrgencyLevel = UrgencyLevel.UNKNOWN
    completeness_score: float = 0.0  # 0.0 to 1.0
    missing_critical_fields: List[str] = Field(default_factory=list)
    uncertain_fields: List[str] = Field(default_factory=list)
    contradictions: List[str] = Field(default_factory=list)
    related_incident_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    operator_action_recommendations: List[str] = Field(default_factory=list)

class AdaptiveFollowUp(BaseModel):
    id: str = Field(default_factory=lambda: f"QUE-{uuid.uuid4().hex[:6]}")
    question_text: str
    target_field: str
    language: str = "en"
    rationale: str
    is_asked: bool = False
    answer: Optional[str] = None

class IncidentRecord(BaseModel):
    incident_id: str = Field(default_factory=lambda: generate_id("INC"))
    state: IncidentState = IncidentState.RECEIVED
    category: IncidentCategory = IncidentCategory.ROAD_ACCIDENT
    urgency: UrgencyLevel = UrgencyLevel.HIGH
    connection_state: ConnectionState = ConnectionState.CONNECTED
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    language: str = "en"
    
    # Natural conversation data
    raw_transcript: str = ""
    audio_reference_url: Optional[str] = None
    caller_phone: Optional[str] = None
    caller_name: Optional[str] = None
    
    # Structured Extracted Fields with Provenance
    fields: Dict[str, FieldProvenance] = Field(default_factory=dict)
    
    # Dual-Location Intelligence
    # Nothing said yet = MISSING, not "caller reported"
    locations: DualLocation = Field(default_factory=lambda: DualLocation(
        caller_location=LocationRecord(description="Pending caller location", verification_status=VerificationStatus.MISSING, confidence=0.0),
        incident_location=LocationRecord(description="Pending incident location", verification_status=VerificationStatus.MISSING, confidence=0.0)
    ))
    
    # Multi-Agent State
    reasoning: AgentReasoning = Field(default_factory=AgentReasoning)
    follow_up_queue: List[AdaptiveFollowUp] = Field(default_factory=list)
    coordination_actions: List[CoordinationAction] = Field(default_factory=list)
    
    # Operator Supervised Metadata
    assigned_operator: Optional[str] = "Operator-1 (Command Center)"
    operator_acknowledged: bool = False
    operator_notes: List[str] = Field(default_factory=list)
    is_merged: bool = False
    merged_into_id: Optional[str] = None
