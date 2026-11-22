"""
RESQ 4.0 Voice Intelligence Agent (Agent 1)
Understands fragmented Tamil and English emergency conversations, detects intent,
extracts structured fields, separates caller vs incident locations, and generates
adaptive clarification questions without delaying human operator escalation.

Extraction pipeline:
  1. Try Gemini API structured extraction (if GEMINI_API_KEY is set)
  2. Try Nominatim geocoding for location strings
  3. Fall back to keyword rules for any fields Gemini couldn't fill
"""
import asyncio
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

# ── Keyword fallbacks ────────────────────────────────────────────────────────

CATEGORY_KEYWORDS = {
    IncidentCategory.FIRE_HAZARD: ["fire", "flames", "smoke", "burning", "தீ விபத்து", "தீ", "நெருப்பு", "புகை"],
    IncidentCategory.MEDICAL_EMERGENCY: ["chest pain", "heart attack", "collapsed", "breathing", "unconscious", "மருத்துவ", "மாரடைப்பு"],
    IncidentCategory.INDUSTRIAL_LEAK: ["chemical", "gas leak", "fumes", "leak", "விஷம்"],
    IncidentCategory.STRUCTURAL_COLLAPSE: ["collapse", "building fell", "wall broke", "இடிந்து"],
    IncidentCategory.ROAD_ACCIDENT: ["accident", "crash", "collision", "hit", "bike", "car", "lorry", "bus", "விபத்து"],
}

LANDMARK_COORDS = {
    "anna flyover": ("Anna Flyover / Gemini Circle Bridge", 13.0524, 80.2508),
    "anna bridge": ("Anna Flyover / Gemini Circle Bridge", 13.0524, 80.2508),
    "அண்ணா மேம்பாலம்": ("Anna Flyover / Gemini Circle Bridge", 13.0524, 80.2508),
    "bridge": ("Unspecified Bridge Landmark", 13.0450, 80.2400),
    "மேம்பாலம்": ("Unspecified Bridge Landmark", 13.0450, 80.2400),
    "பாலம்": ("Unspecified Bridge Landmark", 13.0450, 80.2400),
    "highway": ("Highway Bypass Section", 13.0100, 80.2000),
    "bypass": ("Highway Bypass Section", 13.0100, 80.2000),
    "நெடுஞ்சாலை": ("Highway Bypass Section", 13.0100, 80.2000),
    "market": ("Central Market Area", 13.0827, 80.2707),
    "சந்தை": ("Central Market Area", 13.0827, 80.2707),
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
    def process_utterance(
        self,
        incident: IncidentRecord,
        raw_text: str,
        language: str = "en",
        audio_url: Optional[str] = None
    ) -> IncidentRecord:
        """
        Processes voice transcript into structured provenance fields.
        Tries Gemini extraction first, falls back to keyword rules.
        """
        incident.raw_transcript = (incident.raw_transcript + " " + raw_text).strip()
        incident.language = language
        if audio_url:
            incident.audio_reference_url = audio_url

        now = datetime.utcnow().isoformat()

        # Try Gemini extraction (async in sync context via asyncio)
        gemini_data = None
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    future = pool.submit(asyncio.run, self._try_gemini(raw_text))
                    gemini_data = future.result(timeout=10)
            else:
                gemini_data = loop.run_until_complete(self._try_gemini(raw_text))
        except Exception as e:
            print(f"[VoiceAgent] Gemini extraction skipped: {e}")

        if gemini_data:
            self._apply_gemini_data(incident, gemini_data, raw_text, now)
            extraction_method = "Gemini AI Structured Extraction"
        else:
            self._apply_keyword_rules(incident, raw_text, raw_text.lower(), now)
            extraction_method = "Keyword Rule Engine (Gemini unavailable)"

        # Geocode incident location if coordinates are still None
        if incident.locations.incident_location.latitude is None:
            geocoded = None
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        future = pool.submit(asyncio.run,
                                             self._try_geocode(incident.locations.incident_location.description))
                        geocoded = future.result(timeout=8)
                else:
                    geocoded = loop.run_until_complete(
                        self._try_geocode(incident.locations.incident_location.description))
            except Exception as e:
                print(f"[VoiceAgent] Geocoding skipped: {e}")

            if geocoded:
                incident.locations.incident_location.latitude = geocoded["lat"]
                incident.locations.incident_location.longitude = geocoded["lon"]
                incident.locations.incident_location.precision = "Street Level (Nominatim)"
                incident.locations.incident_location.notes = (
                    f"Geocoded via Nominatim. Confidence: {geocoded['confidence']:.2f}. "
                    "Verify before dispatch."
                )

        # Always generate adaptive follow-ups
        self._generate_adaptive_follow_up(incident, language)

        if incident.state == IncidentState.RECEIVED:
            incident.state = IncidentState.INFORMATION_GATHERING

        db_engine.save_incident(incident)

        evt = TimelineEvent(
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
        )
        db_engine.log_event(evt)
        return incident

    # ── Gemini path ──────────────────────────────────────────────────────────

    async def _try_gemini(self, text: str):
        from backend.services.gemini_service import extract_incident_data
        return await extract_incident_data(text)

    async def _try_geocode(self, address: str):
        from backend.services.geocoding_service import geocode_location
        return await geocode_location(address)

    def _apply_gemini_data(self, incident: IncidentRecord, data: dict, raw_text: str, now: str):
        """Apply Gemini-extracted fields with provenance tracking."""
        # Category
        cat_str = data.get("category", "Road Accident")
        for cat in IncidentCategory:
            if cat.value.lower() == cat_str.lower():
                incident.category = cat
                break

        # Urgency
        urgency_map = {
            "CRITICAL": UrgencyLevel.CRITICAL,
            "HIGH": UrgencyLevel.HIGH,
            "MEDIUM": UrgencyLevel.MEDIUM,
            "LOW": UrgencyLevel.LOW,
        }
        incident.urgency = urgency_map.get(data.get("urgency", "HIGH"), UrgencyLevel.HIGH)

        # Injuries
        injuries = data.get("injuries")
        count = data.get("affected_count")
        if injuries:
            incident.fields["reported_injuries"] = FieldProvenance(
                field_name="reported_injuries",
                current_value=injuries,
                original_value=injuries,
                source=ProvenanceSource.AI_EXTRACTION,
                timestamp=now,
                confidence=float(data.get("confidence", 0.85)),
                verification_status=VerificationStatus.AI_INFERRED_AWAITING_CONFIRMATION,
                extraction_method="Gemini AI Structured Extraction",
                transcript_reference=raw_text
            )
            incident.urgency = UrgencyLevel.CRITICAL
        if count is not None:
            incident.fields["affected_count"] = FieldProvenance(
                field_name="affected_count",
                current_value=count,
                original_value=count,
                source=ProvenanceSource.AI_EXTRACTION,
                timestamp=now,
                confidence=float(data.get("confidence", 0.85)),
                verification_status=VerificationStatus.AI_INFERRED_AWAITING_CONFIRMATION,
                extraction_method="Gemini AI Structured Extraction",
                transcript_reference=raw_text
            )

        # Immediate danger
        if data.get("immediate_danger"):
            incident.fields["immediate_danger"] = FieldProvenance(
                field_name="immediate_danger",
                current_value="Active Hazard / Vulnerable Victims Reported",
                original_value="Active Hazard / Vulnerable Victims Reported",
                source=ProvenanceSource.AI_EXTRACTION,
                timestamp=now,
                confidence=float(data.get("confidence", 0.9)),
                verification_status=VerificationStatus.AI_INFERRED_AWAITING_CONFIRMATION,
                extraction_method="Gemini AI Structured Extraction",
                transcript_reference=raw_text
            )

        # Locations
        incident_loc_str = data.get("incident_location")
        caller_loc_str = data.get("caller_location")
        caller_separated = data.get("caller_separated", False)
        confidence = float(data.get("confidence", 0.75))

        incident.locations.is_separated = caller_separated
        if caller_separated:
            incident.locations.separation_rationale = "AI determined caller is not at the incident scene"

        if incident_loc_str:
            incident.locations.incident_location = LocationRecord(
                description=incident_loc_str,
                source=ProvenanceSource.AI_EXTRACTION,
                timestamp=now,
                precision="Text Description (Geocoding pending)",
                verification_status=VerificationStatus.UNCERTAIN,
                confidence=confidence,
                notes="Extracted by Gemini AI. Coordinates pending geocoding. Verify before dispatch."
            )
        
        if caller_separated and caller_loc_str:
            incident.locations.caller_location = LocationRecord(
                description=caller_loc_str,
                source=ProvenanceSource.AI_EXTRACTION,
                timestamp=now,
                precision="Caller-stated location",
                verification_status=VerificationStatus.CALLER_REPORTED,
                confidence=confidence
            )

        # Note ambiguities
        ambiguities = data.get("ambiguities", [])
        if ambiguities:
            incident.fields["ai_ambiguities"] = FieldProvenance(
                field_name="ai_ambiguities",
                current_value="; ".join(ambiguities),
                original_value="; ".join(ambiguities),
                source=ProvenanceSource.AI_EXTRACTION,
                timestamp=now,
                confidence=1.0,
                verification_status=VerificationStatus.AI_INFERRED_AWAITING_CONFIRMATION,
                extraction_method="Gemini AI Ambiguity Detection"
            )

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
        return IncidentCategory.ROAD_ACCIDENT

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
        lat, lng = None, None

        for keyword, (desc, klat, klng) in LANDMARK_COORDS.items():
            if keyword in text_lower or keyword in text:
                incident_loc_str = desc
                lat, lng = klat, klng
                break

        if caller_away:
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

        if incident_loc_str:
            incident.locations.incident_location = LocationRecord(
                description=incident_loc_str,
                latitude=lat,
                longitude=lng,
                source=ProvenanceSource.CALLER_VOICE,
                timestamp=timestamp,
                precision="Landmark / Approximate (requires exact pin)",
                verification_status=VerificationStatus.UNCERTAIN,
                confidence=0.60,
                notes="Landmark identified from voice keyword. Exact GPS unverified — confirm before dispatch."
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
