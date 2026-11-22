"""
RESQ 4.0 Core Enumerations
Defines the authoritative state machine states, verification tags, provenance sources,
and action lifecycle tracking.
"""
from enum import Enum

class IncidentState(str, Enum):
    RECEIVED = "RECEIVED"
    INFORMATION_GATHERING = "INFORMATION_GATHERING"
    VALIDATION = "VALIDATION"
    OPERATOR_REVIEW = "OPERATOR_REVIEW"
    ESCALATION_PENDING = "ESCALATION_PENDING"
    ESCALATION_SENT = "ESCALATION_SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ASSIGNED = "ASSIGNED"
    ACTIVE_MONITORING = "ACTIVE_MONITORING"
    RESOLUTION_REVIEW = "RESOLUTION_REVIEW"
    CLOSED = "CLOSED"

class VerificationStatus(str, Enum):
    CALLER_REPORTED = "CALLER_REPORTED"
    INDEPENDENTLY_VERIFIED = "INDEPENDENTLY_VERIFIED"
    AI_INFERRED_AWAITING_CONFIRMATION = "AI_INFERRED_AWAITING_CONFIRMATION"
    UNCERTAIN = "UNCERTAIN"
    CONFLICTING = "CONFLICTING"
    MISSING = "MISSING"
    UNAVAILABLE = "UNAVAILABLE"

class ProvenanceSource(str, Enum):
    CALLER_VOICE = "CALLER_VOICE"
    CALLER_TEXT = "CALLER_TEXT"
    AI_EXTRACTION = "AI_EXTRACTION"
    OPERATOR_OVERRIDE = "OPERATOR_OVERRIDE"
    CROSS_REFERENCE = "CROSS_REFERENCE"
    SYSTEM_RECOVERY = "SYSTEM_RECOVERY"
    DEVICE_GPS = "DEVICE_GPS"  # shared by the caller's phone/browser, not independently verified

class ActionStatus(str, Enum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ACCEPTED_OR_ASSIGNED = "ACCEPTED_OR_ASSIGNED"
    FAILED = "FAILED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    CANCELLED = "CANCELLED"

class UrgencyLevel(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"

class ConnectionState(str, Enum):
    CONNECTED = "CONNECTED"
    SILENCE_DETECTED = "SILENCE_DETECTED"
    DISCONNECTED = "DISCONNECTED"
    RECONNECTED = "RECONNECTED"

class IncidentCategory(str, Enum):
    ROAD_ACCIDENT = "Road Accident"
    MEDICAL_EMERGENCY = "Medical Emergency"
    FIRE_HAZARD = "Fire Hazard"
    STRUCTURAL_COLLAPSE = "Structural Collapse"
    INDUSTRIAL_LEAK = "Industrial Hazard / Leak"
    CRIMINAL_VIOLENCE = "Criminal Incident"
    NATURAL_DISASTER = "Flood / Natural Disaster"
    OTHER = "Other Emergency"
