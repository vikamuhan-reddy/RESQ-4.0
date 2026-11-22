"""
RESQ 4.0 Dispatch delivery.
Builds the department message from a fixed template (not AI-written) and delivers it to that
department's Telegram group. Without a bot token it does a clearly labelled simulated delivery.
"""
import os
from typing import Tuple

import httpx

from backend.models.incident import IncidentRecord, CoordinationAction
from backend.models.enums import VerificationStatus

# action_type -> .env variable holding that department's Telegram chat id
CHAT_ENV = {
    "DISPATCH_EMS": "TELEGRAM_CHAT_AMBULANCE",
    "NOTIFY_FIRE_RESCUE": "TELEGRAM_CHAT_FIRE",
    "ALERT_POLICE": "TELEGRAM_CHAT_POLICE",
    "ALERT_TRAFFIC_POLICE": "TELEGRAM_CHAT_POLICE",
}


def format_message(incident: IncidentRecord, action: CoordinationAction) -> str:
    loc = incident.locations.incident_location
    f = incident.fields
    if loc.verification_status == VerificationStatus.INDEPENDENTLY_VERIFIED and loc.latitude is not None:
        where = f"{loc.description} (confirmed)\nhttps://maps.google.com/?q={loc.latitude},{loc.longitude}"
    else:
        where = f"{loc.description} (caller's words, NOT confirmed)"
    injuries = f["reported_injuries"].current_value if "reported_injuries" in f else "none reported"
    if "affected_count" in f:
        injuries += f" ({f['affected_count'].current_value} people)"
    hazards = f["immediate_danger"].current_value if "immediate_danger" in f else "none reported"
    caller = "at the scene" if not incident.locations.is_separated else f"NOT at scene ({incident.locations.caller_location.description})"
    unknown = ", ".join(incident.reasoning.missing_critical_fields) or "nothing flagged"
    return "\n".join([
        "RESQ DISPATCH - SIMULATION (demo, not a real emergency)",
        f"To: {action.target_agency}",
        f"Type: {incident.category.value} | Urgency: {incident.urgency.value}",
        f"Location: {where}",
        f"Injuries: {injuries}",
        f"Hazards: {hazards}",
        f"Caller: {caller}; callback {incident.caller_phone or 'unknown'}",
        f"Still unknown: {unknown}",
        f"Incident {incident.incident_id} | approved by {action.operator_id}",
    ])


async def deliver(incident: IncidentRecord, action: CoordinationAction) -> Tuple[bool, str]:
    """Returns (delivered, note). Never raises; the note is shown to the operator."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        return True, "Simulated delivery (Telegram not configured)"
    chat_env = CHAT_ENV.get(action.action_type)
    chat_id = os.getenv(chat_env) if chat_env else None
    if not chat_id:
        return False, f"No Telegram chat configured for {action.target_agency} ({chat_env or action.action_type})"
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": format_message(incident, action)},
            )
        body = r.json()
    except Exception as e:
        return False, f"Telegram unreachable ({type(e).__name__})"  # never echo the URL: it contains the token
    if body.get("ok"):
        return True, f"Delivered to {action.target_agency} on Telegram (message {body['result']['message_id']})"
    return False, f"Telegram refused: {body.get('description', r.status_code)}"
