"""
RESQ 4.0 Voice Intelligence Agent (Agent 1)
Turns a fragmented Tamil/English emergency conversation into structured fields with provenance,
separates caller location from incident location, and queues the next question to ask.

Extraction: Gemini structured output on the whole conversation so far; keyword rules as fallback.
"""
from typing import Optional
from datetime import datetime

from backend.models.incident import (
    IncidentRecord,
    FieldProvenance,
    LocationRecord,
    AdaptiveFollowUp,
    TimelineEvent
)
from backend.models.enums import (
    IncidentCategory,
    VerificationStatus,
    ProvenanceSource,
    UrgencyLevel,
    IncidentState
)
from backend.core.persistence import db_engine
from backend.core.orchestrator import orchestrator
from backend.services.gemini_service import extract_incident_data, Extraction

# ── Keyword fallbacks ────────────────────────────────────────────────────────

CATEGORY_KEYWORDS = {
    IncidentCategory.FIRE_HAZARD: ["fire", "flames", "smoke", "burning", "தீ விபத்து", "தீ", "நெருப்பு", "புகை"],
    IncidentCategory.MEDICAL_EMERGENCY: ["chest pain", "heart attack", "collapsed", "breathing", "unconscious", "மருத்துவ", "மாரடைப்பு"],
    IncidentCategory.INDUSTRIAL_LEAK: ["chemical", "gas leak", "fumes", "leak", "விஷம்"],
    IncidentCategory.STRUCTURAL_COLLAPSE: ["collapse", "building fell", "wall broke", "இடிந்து"],
    IncidentCategory.ROAD_ACCIDENT: ["accident", "crash", "collision", "hit", "bike", "car", "lorry", "bus", "விபத்து"],
}

# Keyword -> landmark name. No coordinates on purpose: a spoken landmark is never a map pin
# until an operator confirms it.
LANDMARKS = {
    "anna flyover": "Anna Flyover / Gemini Circle",
    "anna bridge": "Anna Flyover / Gemini Circle",
    "அண்ணா மேம்பாலம்": "Anna Flyover / Gemini Circle",
    "bridge": "A bridge (unspecified)",
    "மேம்பாலம்": "A flyover (unspecified)",
    "பாலம்": "A bridge (unspecified)",
    "highway": "A highway (unspecified)",
    "bypass": "A bypass road (unspecified)",
    "நெடுஞ்சாலை": "A highway (unspecified)",
    "market": "A market (unspecified)",
    "சந்தை": "A market (unspecified)",
}

CALLER_AWAY_PHRASES = [
    "not at the exact place", "not at the spot", "calling from my office",
    "calling from office", "calling from home", "driving past",
    "saw it from afar", "not there", "நான் இங்க இல்ல", "அலுவலகத்தில் இருந்து"
]

DANGER_KEYWORDS = ["fire", "smoke", "explosion", "leak", "trapped", "unconscious",
                   "bleeding", "தீ", "புகை", "மயக்கம்"]

# ── Main Agent ───────────────────────────────────────────────────────────────

class VoiceIntelligenceAgent:
    async def process_utterance(
        self,
        incident: IncidentRecord,
        raw_text: str,
        language: str = "en",
        audio_url: Optional[str] = None
    ) -> IncidentRecord:
        """
        Re-reads the whole conversation so far, not just the latest sentence, so a follow-up
        like "I'm calling from my office" can't wipe what was said before.
        Gemini first; keyword rules if Gemini is not configured or fails.
        """
        incident.raw_transcript = (incident.raw_transcript + " " + raw_text).strip()
        incident.language = language
        if audio_url:
            incident.audio_reference_url = audio_url
        now = datetime.utcnow().isoformat()
        transcript = incident.raw_transcript
        db_engine.add_turn(incident.incident_id, "caller", raw_text.strip(), language)

        extraction = None
        try:
            extraction = await extract_incident_data(self._conversation(incident.incident_id))
        except Exception as e:
            # Real AI failure: log it, flag the incident for the operator, carry on with keyword rules
            orchestrator.handle_ai_service_failure(incident, "Gemini extraction", f"{type(e).__name__}: {e}")

        if extraction:
            self._apply_extraction(incident, extraction, transcript, now)
            extraction_method = "Gemini structured extraction"
        else:
            self._apply_keyword_rules(incident, transcript, transcript.lower(), now)
            self._generate_adaptive_follow_up(incident, language)
            extraction_method = "Keyword rules (AI unavailable)"

        if incident.state == IncidentState.RECEIVED:
            orchestrator.advance(incident, IncidentState.INFORMATION_GATHERING, "Voice Intelligence Agent", "First caller statement processed")

        db_engine.save_incident(incident)
        if incident.follow_up_queue:
            q = incident.follow_up_queue[0]
            db_engine.add_turn(incident.incident_id, "resq", q.question_text, q.language, q.rationale)

        db_engine.log_event(TimelineEvent(
            incident_id=incident.incident_id,
            event_type="AGENT_INFERENCE",
            actor="Voice Intelligence Agent",
            summary=(
                f"Processed intake ({language.upper()}) via {extraction_method}: "
                f"category='{incident.category.value}', "
                f"injuries={'yes' if 'reported_injuries' in incident.fields else 'none stated'}"
            ),
            details={
                "extraction_method": extraction_method,
                "extracted_fields": list(incident.fields.keys()),
                "caller_loc": incident.locations.caller_location.description,
                "incident_loc": incident.locations.incident_location.description,
                "location_separated": incident.locations.is_separated
            }
        ))
        return incident

    # ── Gemini path ──────────────────────────────────────────────────────────

    def _conversation(self, incident_id: str) -> str:
        """The call so far with speakers labelled, so Gemini knows which questions were already asked."""
        return "\n".join(
            f"{'Caller' if t['speaker'] == 'caller' else 'RESQ asked'}: {t['text']}" for t in db_engine.get_turns(incident_id)
        )

    def _apply_extraction(self, incident: IncidentRecord, e: Extraction, transcript: str, now: str):
        incident.category = IncidentCategory(e.category)
        incident.urgency = UrgencyLevel(e.urgency)

        def put(name: str, value):
            existing = incident.fields.get(name)
            if existing and existing.source == ProvenanceSource.OPERATOR_OVERRIDE:
                return  # never overwrite what an operator corrected or verified
            if value in (None, "", []):
                incident.fields.pop(name, None)  # whole conversation re-read: absent now means not said
                return
            incident.fields[name] = FieldProvenance(
                field_name=name,
                current_value=value,
                original_value=value,
                source=ProvenanceSource.AI_EXTRACTION,
                timestamp=now,
                confidence=e.confidence,
                verification_status=VerificationStatus.AI_INFERRED_AWAITING_CONFIRMATION,
                extraction_method="Gemini structured extraction",
                transcript_reference=transcript
            )

        put("reported_injuries", e.injuries)
        put("affected_count", e.affected_count)
        put("immediate_danger", "; ".join(e.hazards))

        loc = incident.locations
        if loc.incident_location.verification_status != VerificationStatus.INDEPENDENTLY_VERIFIED:
            prev = loc.incident_location
            if e.incident_location_text:
                loc.incident_location = LocationRecord(
                    description=e.incident_location_text,
                    source=ProvenanceSource.AI_EXTRACTION,
                    timestamp=now,
                    precision="Caller's words (not on map until an operator confirms)",
                    verification_status=VerificationStatus.UNCERTAIN,
                    confidence=e.confidence,
                    notes="From the caller's description. Not geocoded; confirm before dispatch.",
                    search_query=e.location_search_query
                )
                if prev.latitude is not None:
                    # Keep the current suggested pin; the background lookup moves or clears it if the place changed
                    new = loc.incident_location
                    new.latitude, new.longitude, new.precision, new.notes = prev.latitude, prev.longitude, prev.precision, prev.notes
                    new.suggested_for = prev.suggested_for
            else:
                loc.incident_location = LocationRecord(
                    description="Location not given yet",
                    source=ProvenanceSource.AI_EXTRACTION,
                    timestamp=now,
                    precision="Unknown",
                    verification_status=VerificationStatus.MISSING,
                    confidence=0.0
                )

        loc.is_separated = not e.caller_on_scene
        loc.separation_rationale = "Caller says they are not at the incident" if loc.is_separated else None
        if loc.caller_location.source != ProvenanceSource.DEVICE_GPS:  # a device fix beats words
            loc.caller_location = LocationRecord(
                description=(e.caller_location_text or "Away from the scene (not said where)") if loc.is_separated else "At the incident scene",
                source=ProvenanceSource.AI_EXTRACTION,
                timestamp=now,
                precision="Caller-stated",
                verification_status=VerificationStatus.CALLER_REPORTED,
                confidence=e.confidence
            )

        incident.follow_up_queue.clear()
        if e.missing:
            incident.follow_up_queue.append(AdaptiveFollowUp(
                question_text=e.next_question_ta if incident.language == "ta" else e.next_question_en,
                target_field=e.missing[0],
                language=incident.language,
                rationale="Still needed: " + ", ".join(e.missing)
            ))

    # ── Keyword fallback path ────────────────────────────────────────────────

    def _apply_keyword_rules(self, incident: IncidentRecord, text: str, text_lower: str, now: str):
        incident.category = self._detect_category(text, text_lower)
        injuries_found, count_val = self._extract_injuries(text, text_lower)

        if injuries_found:
            incident.fields["reported_injuries"] = FieldProvenance(
                field_name="reported_injuries",
                current_value=injuries_found,
                original_value=injuries_found,
                source=ProvenanceSource.CALLER_VOICE,
                timestamp=now,
                confidence=0.72,
                verification_status=VerificationStatus.CALLER_REPORTED,
                extraction_method="Keyword Rule Engine",
                transcript_reference=text
            )
            incident.urgency = UrgencyLevel.CRITICAL

        if count_val is not None:
            incident.fields["affected_count"] = FieldProvenance(
                field_name="affected_count",
                current_value=count_val,
                original_value=count_val,
                source=ProvenanceSource.CALLER_VOICE,
                timestamp=now,
                confidence=0.68,
                verification_status=VerificationStatus.CALLER_REPORTED,
                extraction_method="Numeric Keyword Parser",
                transcript_reference=text
            )

        if any(w in text_lower for w in DANGER_KEYWORDS):
            incident.fields["immediate_danger"] = FieldProvenance(
                field_name="immediate_danger",
                current_value="Active Hazard / Vulnerable Victims Reported",
                original_value="Active Hazard / Vulnerable Victims Reported",
                source=ProvenanceSource.CALLER_VOICE,
                timestamp=now,
                confidence=0.80,
                verification_status=VerificationStatus.CALLER_REPORTED,
                extraction_method="Hazard Keyword Classifier"
            )

        self._extract_dual_locations(incident, text, text_lower, now)

    def _detect_category(self, text: str, text_lower: str) -> IncidentCategory:
        for cat, keywords in CATEGORY_KEYWORDS.items():
            if any(w in text_lower for w in keywords):
                return cat
        return IncidentCategory.OTHER

    def _extract_injuries(self, text: str, text_lower: str):
        injuries = None
        count = None
        if "two people" in text_lower or "2 people" in text_lower or "இரண்டு பேர்" in text:
            count = 2; injuries = "Two individuals injured"
        elif "one person" in text_lower or "1 person" in text_lower or "ஒருவர்" in text:
            count = 1; injuries = "One individual injured"
        elif "three" in text_lower or "3 people" in text_lower or "மூன்று பேர்" in text:
            count = 3; injuries = "Three individuals injured"
        elif any(w in text_lower for w in ["injur", "hurt", "bleeding", "unconscious", "casualt", "காயம்", "ரத்தம்"]):
            injuries = "Injuries reported by caller (count unconfirmed)"
        return injuries, count

    def _extract_dual_locations(self, incident: IncidentRecord, text: str, text_lower: str, timestamp: str):
        caller_away = any(phrase in text_lower for phrase in CALLER_AWAY_PHRASES) or \
                      "நான் இங்க இல்ல" in text or "அலுவலகத்தில் இருந்து" in text

        incident_loc_str = None
        for keyword, desc in LANDMARKS.items():
            if keyword in text_lower or keyword in text:
                incident_loc_str = desc
                break

        if caller_away and incident.locations.caller_location.source == ProvenanceSource.DEVICE_GPS:
            incident.locations.is_separated = True
            incident.locations.separation_rationale = "Caller explicitly stated they are not at the incident location"
        elif caller_away:
            incident.locations.is_separated = True
            incident.locations.separation_rationale = "Caller explicitly stated they are not at the incident location"
            caller_desc = "Caller Office / Remote Location" if ("office" in text_lower or "அலுவலக" in text) \
                          else "Remote / In-transit location"
            incident.locations.caller_location = LocationRecord(
                description=caller_desc,
                latitude=None,  # Don't pin caller without GPS
                longitude=None,
                source=ProvenanceSource.CALLER_VOICE,
                timestamp=timestamp,
                precision="Approximate / Remote caller (unverified)",
                verification_status=VerificationStatus.CALLER_REPORTED,
                confidence=0.60,
                notes="Caller stated they are observing or reporting remotely. No GPS available."
            )

        if incident.locations.incident_location.verification_status == VerificationStatus.INDEPENDENTLY_VERIFIED:
            return  # an operator-confirmed location is never overwritten by keyword matching

        if incident_loc_str:
            incident.locations.incident_location = LocationRecord(
                description=incident_loc_str,
                source=ProvenanceSource.CALLER_VOICE,
                timestamp=timestamp,
                precision="Landmark from caller's words (not on map until confirmed)",
                verification_status=VerificationStatus.UNCERTAIN,
                confidence=0.60,
                notes="Landmark matched by keyword. Not geocoded; confirm before dispatch."
            )
        elif not incident.locations.incident_location.description or \
             incident.locations.incident_location.description == "Pending incident location":
            incident.locations.incident_location = LocationRecord(
                description="Location not specified",
                source=ProvenanceSource.CALLER_VOICE,
                timestamp=timestamp,
                precision="Unknown",
                verification_status=VerificationStatus.MISSING,
                confidence=0.0,
                notes="Caller did not specify the incident location."
            )

    def _generate_adaptive_follow_up(self, incident: IncidentRecord, language: str):
        incident.follow_up_queue.clear()
        if incident.locations.incident_location.verification_status in [VerificationStatus.MISSING, VerificationStatus.UNCERTAIN]:
            q = AdaptiveFollowUp(
                question_text=(
                    "விபத்து நடக்கும் இடம் அல்லது அருகில் உள்ள முக்கிய கட்டிடம், அடையாளம் என்ன?"
                    if language == "ta" else
                    "Can you identify the nearest road, junction, building, or landmark to the incident?"
                ),
                target_field="incident_location_landmark",
                language=language,
                rationale="Incident location is uncertain or missing."
            )
            incident.follow_up_queue.append(q)

        if "reported_injuries" in incident.fields and "affected_count" not in incident.fields:
            q = AdaptiveFollowUp(
                question_text=(
                    "எத்தனை நபர்கள் காயமடைந்துள்ளனர்? யாராவது மயக்கத்தில் உள்ளார்களா?"
                    if language == "ta" else
                    "How many people appear injured, and is anyone unconscious or in immediate danger?"
                ),
                target_field="affected_count",
                language=language,
                rationale="Injuries reported but count unconfirmed."
            )
            incident.follow_up_queue.append(q)


voice_agent = VoiceIntelligenceAgent()
