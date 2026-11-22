"""
RESQ 4.0 FastAPI Application Entrypoint
Exposes the complete REST API and Server-Sent Events (SSE) live stream
for the Operator Intelligence Dashboard, Agent Orchestration, and Continuity Engine.
"""
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass
import os
import asyncio
import json
from typing import Optional, Dict, Any
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.core.persistence import db_engine
from backend.core.orchestrator import orchestrator, NotFound, Conflict
from backend.agents.voice_agent import voice_agent
from backend.agents.reasoning_agent import reasoning_agent
from backend.agents.coordination_agent import coordination_agent
from backend.services.gemini_service import transcribe_audio as gemini_transcribe

app = FastAPI(
    title="RESQ 4.0 Emergency Intelligence Platform",
    description="Failure-Aware Agentic Emergency Intelligence & Incident Continuity Platform",
    version="4.0.0"
)

@app.exception_handler(NotFound)
async def _not_found(_: Request, exc: NotFound):
    return JSONResponse({"detail": str(exc)}, status_code=404)

@app.exception_handler(Conflict)
async def _conflict(_: Request, exc: Conflict):
    return JSONResponse({"detail": str(exc)}, status_code=409)

import os as _os
_ALLOWED_ORIGINS = [o.strip() for o in _os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000"
).split(",") if o.strip()]

# Enable CORS — restrict origins in production via ALLOWED_ORIGINS env var
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Operator-ID"],
)

DISPATCH_MODE = _os.getenv("DISPATCH_MODE", "simulation")

# Client listeners for real-time SSE stream
sse_subscribers = set()

async def broadcast_event(event_type: str, data: Dict[str, Any]):
    message = json.dumps({"event": event_type, "data": data, "timestamp": datetime.utcnow().isoformat()})
    dead_subscribers = set()
    for queue in sse_subscribers:
        try:
            await queue.put(message)
        except Exception:
            dead_subscribers.add(queue)
    for dead in dead_subscribers:
        sse_subscribers.remove(dead)

# Request Models
class CreateIncidentRequest(BaseModel):
    category: str = "Road Accident"
    language: str = "en"

class VoiceIntakeRequest(BaseModel):
    transcript: str
    language: str = "en"
    audio_url: Optional[str] = None

class DisconnectRequest(BaseModel):
    reason: str = "Caller network dropped unexpectedly"

class FieldOverrideRequest(BaseModel):
    field_name: str
    new_value: Any
    reason: str
    operator_id: str = "Operator-1"

class ProposeActionRequest(BaseModel):
    action_type: str
    target_agency: str
    idempotency_key: Optional[str] = None

class ApproveActionRequest(BaseModel):
    action_id: str
    operator_id: str = "Operator-1"

class AcknowledgeRequest(BaseModel):
    operator_id: str = "Operator-1"

class AgencyAckRequest(BaseModel):
    action_id: str
    responder_ref: str = "AMBULANCE-UNIT-108"

# ----------------- Transcription Endpoint -----------------

@app.post("/api/transcribe")
async def transcribe_audio(request: Request):
    """
    Accepts audio blob (multipart/form-data) and returns transcript.
    Audio is sent inline to Gemini (nothing stored server-side); on any problem the
    browser falls back to its own speech-recognition text.
    """
    form = await request.form()
    audio_file = form.get("audio")
    if not audio_file:
        raise HTTPException(status_code=400, detail="No audio file provided")
    audio_bytes = await audio_file.read()
    if len(audio_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio too large (10 MB max)")

    try:
        transcript = await gemini_transcribe(audio_bytes, audio_file.content_type or "audio/webm")
        if transcript is None:
            return JSONResponse({
                "transcript": None,
                "error": "Transcription unavailable: GEMINI_API_KEY not configured. Please type the report manually.",
                "fallback": "manual"
            })
        return {"transcript": transcript, "source": "gemini_audio"}
    except Exception as e:
        return JSONResponse({
            "transcript": None,
            "error": f"Transcription failed: {str(e)}. Please type the report manually.",
            "fallback": "manual"
        }, status_code=200)

# Mount static folder
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>RESQ 4.0 Running - Static files loading...</h1>")

@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "platform": "RESQ 4.0",
        "tagline": "Listen. Understand. Validate. Recover. Coordinate. Escalate. Learn.",
        "incidents_count": len(db_engine.list_incidents()),
        "continuity_engine": "ACTIVE"
    }

# ----------------- Incidents Management -----------------

@app.get("/api/incidents")
async def list_incidents(category: Optional[str] = None, state: Optional[str] = None):
    all_incidents = db_engine.list_incidents()
    if category:
        all_incidents = [i for i in all_incidents if i.category.value == category]
    if state:
        all_incidents = [i for i in all_incidents if i.state.value == state]
    return all_incidents

@app.post("/api/incidents")
async def create_incident(req: CreateIncidentRequest):
    inc = orchestrator.create_incident(req.category, req.language)
    await broadcast_event("INCIDENT_CREATED", inc.model_dump())
    return inc

@app.get("/api/incidents/{incident_id}")
async def get_incident(incident_id: str):
    inc = db_engine.get_incident(incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")
    return inc

@app.post("/api/incidents/{incident_id}/voice-intake")
async def process_voice_intake(incident_id: str, req: VoiceIntakeRequest):
    inc = db_engine.get_incident(incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")
    
    # Run Voice Agent
    inc = await voice_agent.process_utterance(inc, req.transcript, req.language, req.audio_url)
    
    # Run Incident Reasoning Agent
    inc = reasoning_agent.evaluate_incident(inc)
    
    await broadcast_event("INCIDENT_UPDATED", inc.model_dump())
    return inc

@app.post("/api/incidents/{incident_id}/disconnect")
async def simulate_disconnect(incident_id: str, req: DisconnectRequest):
    inc = orchestrator.handle_caller_disconnection(incident_id, req.reason)
    await broadcast_event("CALLER_DISCONNECTED", inc.model_dump())
    return inc

@app.post("/api/incidents/{incident_id}/acknowledge")
async def operator_acknowledge(incident_id: str, req: AcknowledgeRequest = AcknowledgeRequest()):
    inc = orchestrator.operator_acknowledge(incident_id, req.operator_id)
    await broadcast_event("OPERATOR_ACKNOWLEDGED", inc.model_dump())
    return inc

@app.post("/api/incidents/{incident_id}/override-field")
async def override_field(incident_id: str, req: FieldOverrideRequest):
    inc = orchestrator.operator_override_field(
        incident_id=incident_id,
        field_name=req.field_name,
        new_value=req.new_value,
        reason=req.reason,
        operator_id=req.operator_id
    )
    await broadcast_event("FIELD_OVERRIDDEN", inc.model_dump())
    return inc

@app.post("/api/incidents/{incident_id}/propose-action")
async def propose_coordination_action(incident_id: str, req: ProposeActionRequest):
    inc = db_engine.get_incident(incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")
        
    action = coordination_agent.create_action_proposal(
        incident=inc,
        action_type=req.action_type,
        target_agency=req.target_agency,
        custom_idempotency_key=req.idempotency_key
    )
    updated_inc = db_engine.get_incident(incident_id)
    await broadcast_event("ACTION_PROPOSED", updated_inc.model_dump())
    return action

@app.post("/api/incidents/{incident_id}/approve-action")
async def approve_coordination_action(incident_id: str, req: ApproveActionRequest):
    action = orchestrator.operator_approve_action(
        incident_id=incident_id,
        action_id=req.action_id,
        operator_id=req.operator_id
    )
    # Tag simulation mode on the action
    action.is_simulation = (DISPATCH_MODE != "live")
    action.dispatch_mode = DISPATCH_MODE
    db_engine.save_action(action)
    
    updated_inc = db_engine.get_incident(incident_id)
    await broadcast_event("ACTION_APPROVED", {
        **updated_inc.model_dump(),
        "_simulation_warning": (
            "⚠ SIMULATION MODE: This approval is local only. No real agency was notified."
            if action.is_simulation else "LIVE DISPATCH: Real agency notified."
        )
    })
    return {**action.model_dump(), "_simulation_warning": "⚠ SIMULATION — no real dispatch occurred" if action.is_simulation else ""}

@app.post("/api/incidents/{incident_id}/simulate-ack")
async def simulate_agency_ack(incident_id: str, req: AgencyAckRequest):
    action = orchestrator.simulate_agency_acknowledgment(
        incident_id=incident_id,
        action_id=req.action_id,
        responder_ref=req.responder_ref
    )
    updated_inc = db_engine.get_incident(incident_id)
    await broadcast_event("AGENCY_ACKNOWLEDGED", updated_inc.model_dump())
    return action

@app.get("/api/incidents/{incident_id}/timeline")
async def get_incident_timeline(incident_id: str):
    return db_engine.get_events(incident_id)

# ----------------- Server-Sent Events (SSE) Live Feed -----------------

@app.get("/api/events/stream")
async def event_stream(request: Request):
    queue = asyncio.Queue()
    sse_subscribers.add(queue)
    
    async def event_generator():
        try:
            # Send initial ping
            yield f"data: {json.dumps({'event': 'CONNECTED', 'timestamp': datetime.utcnow().isoformat()})}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                message = await queue.get()
                yield f"data: {message}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            if queue in sse_subscribers:
                sse_subscribers.remove(queue)
                
    return StreamingResponse(event_generator(), media_type="text/event-stream")

# Seed initial demonstration incidents if empty
@app.on_event("startup")
async def startup_event():
    existing = db_engine.list_incidents()
    if not existing:
        # Seed initial rich incident
        inc = orchestrator.create_incident("Road Accident", "ta")
        inc = await voice_agent.process_utterance(
            incident=inc,
            raw_text="வணக்கம், அண்ணா மேம்பாலம் அருகே ஒரு பெரிய விபத்து. இரண்டு பேர் பலத்த காயமடைந்துள்ளனர். நான் இங்க இல்ல, என் அலுவலகத்திலிருந்து பார்க்கிறேன்.",
            language="ta"
        )
        inc = reasoning_agent.evaluate_incident(inc)
        coordination_agent.create_action_proposal(inc, "DISPATCH_EMS", "Emergency Medical Services (108)")
        orchestrator.operator_acknowledge(inc.incident_id, "Operator-Lead-Priya")
        print(f"RESQ 4.0 Initialized with Seed Incident: {inc.incident_id}")
