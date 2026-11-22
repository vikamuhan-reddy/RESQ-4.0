"""
RESQ 4.0 Gemini AI Extraction Service
Uses Google Gemini to extract structured incident data from voice transcripts.
Falls back to None if API key is not set, so voice_agent uses keyword rules.
"""
import os
import json
from typing import Optional, Dict, Any

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

EXTRACTION_PROMPT = """You are an emergency dispatcher AI. Extract structured information from this emergency call transcript.

Transcript:
{transcript}

Respond ONLY with valid JSON in this exact format:
{{
  "category": "<one of: Road Accident, Medical Emergency, Fire Hazard, Structural Collapse, Industrial Hazard / Leak, Criminal Incident, Flood / Natural Disaster, Other Emergency>",
  "injuries": "<description of injuries or null>",
  "affected_count": <integer or null>,
  "incident_location": "<location description or null>",
  "caller_location": "<caller location if different from incident or null>",
  "caller_separated": <true if caller is NOT at the incident scene, false otherwise>,
  "immediate_danger": <true if fire/explosion/unconscious/trapped/bleeding mentioned>,
  "urgency": "<CRITICAL, HIGH, MEDIUM, or LOW>",
  "confidence": <float 0.0-1.0>,
  "ambiguities": ["<list any unclear or contradictory info>"]
}}"""

async def extract_incident_data(transcript: str) -> Optional[Dict[str, Any]]:
    """
    Uses Gemini to extract structured incident fields from a transcript.
    Returns None if GEMINI_API_KEY is not set.
    """
    if not GEMINI_API_KEY:
        return None
    
    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        prompt = EXTRACTION_PROMPT.format(transcript=transcript)
        response = model.generate_content(prompt)
        
        text = response.text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()
        
        data = json.loads(text)
        return data
    except Exception as e:
        print(f"[GeminiService] Extraction failed: {e}")
        return None
