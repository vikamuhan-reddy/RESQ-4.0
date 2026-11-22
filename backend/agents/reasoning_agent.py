"""
RESQ 4.0 Incident Reasoning Agent (Agent 2)
Evaluates structured incident data, assesses information completeness, explains urgency
factors, discovers contradictions, identifies candidate duplicate/related incidents,
and generates actionable recommendations for the human operator.
"""
from typing import List, Dict, Any, Set
from datetime import datetime
import math
import re

from backend.models.incident import IncidentRecord, AgentReasoning, TimelineEvent, LocationRecord
from backend.models.enums import UrgencyLevel, VerificationStatus, IncidentState
from backend.core.persistence import db_engine
from backend.core.orchestrator import orchestrator

DUPLICATE_WINDOW_MIN = 15
# Words that appear in many places' names, so sharing them says nothing (Tamil-English included)
GENERIC_PLACE_WORDS = {
    "chennai", "near", "the", "road", "signal", "junction", "flyover", "bridge", "street", "main", "opposite",
    "side", "kitta", "area", "market", "station", "bus", "stop", "nagar", "unspecified", "location", "not",
    "given", "yet", "pending", "incident", "keela", "mela", "pakkathula", "high", "avenue", "cross", "salai",
}


def place_words(text: str) -> Set[str]:
    """Distinctive words in a place description ('gemini', 'koyambedu'), without generic ones ('road', 'near')."""
    return {t for t in re.split(r"[\s,./()\-]+", (text or "").lower()) if len(t) >= 3 and t not in GENERIC_PLACE_WORDS}


def place_tokens(loc: LocationRecord) -> Set[str]:
    return place_words(f"{loc.search_query or ''} {loc.description or ''}")

def haversine_distance_km(lat1, lon1, lat2, lon2) -> float:
    if None in (lat1, lon1, lat2, lon2):
        return 9999.0
    R = 6371.0 # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

class IncidentReasoningAgent:
    def evaluate_incident(self, incident: IncidentRecord) -> IncidentRecord:
        """
        Runs comprehensive reasoning over the current incident state.
        """
        missing_fields = []
        uncertain_fields = []
        contradictions = []
        operator_recs = []
        
        # 1. Check Critical Fields Completeness
        # Critical fields required for full dispatch readiness:
        # Category, Exact Incident Location, Injuries/Victim Status, Caller Contact
        if incident.locations.incident_location.verification_status in [VerificationStatus.MISSING, VerificationStatus.UNCERTAIN]:
            missing_fields.append("Verified Incident Location / Exact Coordinates")
            uncertain_fields.append("Incident Location is landmark-only / unconfirmed")
            
        if "reported_injuries" not in incident.fields:
            missing_fields.append("Injury Assessment / Victim Count")
            
        if not incident.caller_phone:
            missing_fields.append("Caller Callback Contact")
            
        # Calculate completeness score
        total_key_fields = 4
        present_count = 0
        if incident.category: present_count += 1
        if incident.locations.incident_location.description and incident.locations.incident_location.verification_status != VerificationStatus.MISSING:
            present_count += (0.5 if incident.locations.incident_location.verification_status == VerificationStatus.UNCERTAIN else 1.0)
        if "reported_injuries" in incident.fields: present_count += 1
        if incident.caller_phone: present_count += 1
        
        completeness = min(1.0, round(present_count / total_key_fields, 2))
        
        # 2. Contradiction Detection
        transcript_lower = incident.raw_transcript.lower()
        if ("no one is hurt" in transcript_lower or "no injury" in transcript_lower) and ("reported_injuries" in incident.fields):
            contradictions.append("Caller initially stated 'no one is hurt' but later reported injury details.")
            
        if incident.locations.is_separated and incident.locations.caller_location.description == incident.locations.incident_location.description:
            contradictions.append("Separation flag is True, but caller and incident locations match.")
            
        # 3. Urgency Explanation
        urgency_reasons = []
        if incident.urgency == UrgencyLevel.CRITICAL or "reported_injuries" in incident.fields:
            urgency_reasons.append("Reported injuries involving human life")
        if "immediate_danger" in incident.fields:
            urgency_reasons.append("Active environmental / structural hazard present")
        if incident.locations.is_separated:
            urgency_reasons.append("Caller is remote from incident; real-time ground status may change")
            
        urgency_explanation = "; ".join(urgency_reasons) if urgency_reasons else "Standard priority emergency intake pending further triage."
        
        # 4. Duplicate / Related Incidents Detection
        related_candidates = self._find_related_incidents(incident)
        if related_candidates:
            operator_recs.append(f"Potential duplicate reports detected ({len(related_candidates)} matches). Review candidate list.")
            
        # 5. Formulate Operator Recommendations
        if incident.locations.incident_location.verification_status == VerificationStatus.UNCERTAIN:
            operator_recs.append("Pinpoint exact incident location via cross-referencing street cameras or map lookup.")
        if "reported_injuries" in incident.fields:
            operator_recs.append("Prepare Emergency Medical Service (EMS) preliminary alert with pending location verification.")
        if contradictions:
            operator_recs.append("Resolve identified contradictions with caller callback or field responders.")
            
        # Update Reasoning object
        incident.reasoning = AgentReasoning(
            urgency_explanation=urgency_explanation,
            urgency_level=incident.urgency,
            completeness_score=completeness,
            missing_critical_fields=missing_fields,
            uncertain_fields=uncertain_fields,
            contradictions=contradictions,
            related_incident_candidates=related_candidates,
            operator_action_recommendations=operator_recs
        )
        
        # Advance state to VALIDATION if currently INFORMATION_GATHERING
        if incident.state == IncidentState.INFORMATION_GATHERING:
            orchestrator.advance(incident, IncidentState.VALIDATION, "Incident Reasoning Agent", "Initial assessment complete")
            
        db_engine.save_incident(incident)
        
        evt = TimelineEvent(
            incident_id=incident.incident_id,
            event_type="AGENT_INFERENCE",
            actor="Incident Reasoning Agent",
            summary=f"Evaluated completeness ({int(completeness*100)}%), urgency: {urgency_explanation}",
            details={
                "completeness": completeness,
                "missing_critical": missing_fields,
                "contradictions": contradictions,
                "candidates_count": len(related_candidates)
            }
        )
        db_engine.log_event(evt)
        return incident

    def _find_related_incidents(self, incident: IncidentRecord) -> List[Dict[str, Any]]:
        """
        Scans other incidents for spatial, temporal, and semantic similarity.
        Rule: NEVER auto-merge or auto-reject. Human operator must review.
        """
        if incident.is_merged or incident.locations.incident_location.verification_status == VerificationStatus.MISSING:
            return []
        candidates = []
        loc = incident.locations.incident_location
        my_tokens = place_tokens(loc)
        my_time = datetime.fromisoformat(incident.created_at)

        for other in db_engine.list_incidents():
            other_loc = other.locations.incident_location
            if other.incident_id == incident.incident_id or other.is_merged or other_loc.verification_status == VerificationStatus.MISSING:
                continue
            minutes_apart = abs((datetime.fromisoformat(other.created_at) - my_time).total_seconds()) / 60
            if minutes_apart > DUPLICATE_WINDOW_MIN:
                continue

            # Same place is required (confirmed pins close together, or the same distinctive place name);
            # same category alone would flag every accident in the city
            dist_km = haversine_distance_km(loc.latitude, loc.longitude, other_loc.latitude, other_loc.longitude)
            shared = my_tokens & place_tokens(other_loc)
            reasons = []
            if dist_km <= 0.5:
                reasons.append(f"Confirmed pins {dist_km:.2f} km apart")
            elif shared:
                reasons.append(f"Same place mentioned ({', '.join(sorted(shared))})")
            if not reasons:
                continue
            reasons.append(f"reported {minutes_apart:.0f} min apart")
            if other.category == incident.category:
                reasons.append(f"both {incident.category.value}")

            if reasons:
                candidates.append({
                    "incident_id": other.incident_id,
                    "category": other.category.value,
                    "location_description": other.locations.incident_location.description,
                    "created_at": other.created_at,
                    "distance_km": round(dist_km, 2) if dist_km < 9000 else "Unknown",
                    "similarity_rationale": "; ".join(reasons)
                })
                
        return candidates

reasoning_agent = IncidentReasoningAgent()
