"""
RESQ 4.0 BAND room.
RESQ joins a BAND (band.ai) room as an agent. The voice, reasoning and coordination agents' timeline is
posted there live, and anyone in the room can ask "@RESQ status" or "@RESQ <incident id>" for a summary.
Runs only when BAND_API_KEY is set. That can be an agent key, or your account's key: then RESQ registers
its own "RESQ" agent. On first start it opens a "RESQ live feed" room with you in it (or set BAND_ROOM_ID).
"""
import asyncio
import json
import os
from typing import List, Optional, Tuple

from backend.core.persistence import db_engine
from backend.core.orchestrator import CLOSED_STATES
from backend.models.incident import IncidentRecord, TimelineEvent

# The events that tell the story of a call; per-field noise (overrides, duplicates) stays in the RESQ UI
FEED_EVENTS = {
    "INTAKE_INITIATED", "AGENT_INFERENCE", "STATE_CHANGE", "ACTION_REGISTERED", "PRE_ALERT_SENT",
    "COORDINATION_APPROVED", "DISPATCH_DELIVERED", "DISPATCH_FAILED", "AGENCY_ACKNOWLEDGED",
    "HANDOVER_BRIEF", "HANDOVER_BRIEF_FAILED", "OPERATOR_LOCATION_CONFIRMED", "INCIDENT_MERGED",
    "COMMUNICATION_INTERRUPTION", "AI_SERVICE_FAILURE",
}

AGENT_NAME = "RESQ"
AGENT_DESCRIPTION = "RESQ emergency dispatch co-pilot: posts the live incident timeline and answers '@RESQ status'"
# The registered agent's key and the feed room id (git-ignored: it holds a key)
STATE_FILE = os.getenv("BAND_STATE_PATH") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "band_agent.json")

status = "off"  # off | connecting | connected | error: shown on the dashboard
_room_id: Optional[str] = os.getenv("BAND_ROOM_ID") or None
_loop: Optional[asyncio.AbstractEventLoop] = None
_queue: Optional[asyncio.Queue] = None


def enabled() -> bool:
    return bool(os.getenv("BAND_API_KEY"))


def feed_line(evt: TimelineEvent) -> str:
    flag = "⚠ " if evt.is_failure_event else ""
    return f"{flag}[{evt.actor}] {evt.incident_id[-6:]}: {evt.summary}"


def _on_event(evt: TimelineEvent) -> None:
    """Timeline listener. log_event can run on a worker thread, so hand off to the event loop."""
    if _loop and _queue and evt.event_type in FEED_EVENTS:
        _loop.call_soon_threadsafe(_enqueue, feed_line(evt))


def _enqueue(line: str) -> None:
    if not _queue.full():  # ponytail: drops lines if BAND is down for a long call; a bounded log, not a guarantee
        _queue.put_nowait(line)


def summary(inc: IncidentRecord) -> str:
    loc = inc.locations.incident_location
    actions = ", ".join(f"{a.target_agency}: {a.status.value}" for a in inc.coordination_actions) or "none yet"
    return "\n".join([
        f"{inc.incident_id} | {inc.category.value} | urgency {inc.urgency.value} | {inc.state.value}",
        f"Location: {loc.description} ({loc.verification_status.value})",
        f"Dispatch: {actions}",
        f"Still unknown: {', '.join(inc.reasoning.missing_critical_fields) or 'nothing flagged'}",
    ])


def answer(text: str, incidents: List[IncidentRecord]) -> str:
    """Reply to an @mention: one incident if its id (or last 6 characters) is named, else the open list."""
    asked = [i for i in incidents if i.incident_id[-6:].upper() in text.upper()]
    if asked:
        return "\n\n".join(summary(i) for i in asked)
    open_ = [i for i in incidents if i.state not in CLOSED_STATES and not i.is_merged]
    if not open_:
        return "No open incidents right now."
    lines = [f"Open incidents ({len(open_)}):"] + [
        f"- {i.incident_id[-6:]} {i.category.value}, urgency {i.urgency.value}, {i.state.value}, at {i.locations.incident_location.description}"
        for i in open_
    ]
    return "\n".join(lines + ["Ask \"@RESQ <id>\" for details."])


def _adapter():
    from band.core.simple_adapter import SimpleAdapter

    class RESQAdapter(SimpleAdapter[list]):
        async def on_message(self, msg, tools, history, participants_msg, contacts_msg, *, is_session_bootstrap, room_id):
            global _room_id
            reply = answer(msg.content, db_engine.list_incidents())
            if _room_id != room_id:
                _room_id = room_id
                reply = "Live incident feed will be posted in this room.\n\n" + reply
            await tools.send_message(reply, mentions=[{"id": msg.sender_id}])

    return RESQAdapter()


async def _post(rest, agent_id: str, text: str) -> None:
    from band.client.rest import DEFAULT_REQUEST_OPTIONS, ChatMessageRequest
    from band_rest import ChatMessageRequestMentionsItem
    # Messages need a recipient: mention the people in the room (not other agents, which would make them reply)
    people = await rest.agent_api_participants.list_agent_chat_participants(chat_id=_room_id, request_options=DEFAULT_REQUEST_OPTIONS)
    mentions = [ChatMessageRequestMentionsItem(id=p.id, handle=p.handle)
                for p in (people.data or []) if p.id != agent_id and str(p.type).lower() == "user"]
    await rest.agent_api_messages.create_agent_chat_message(
        chat_id=_room_id, message=ChatMessageRequest(content=text, mentions=mentions), request_options=DEFAULT_REQUEST_OPTIONS)


async def _feed(rest, agent_id: str) -> None:
    while True:
        lines = [await _queue.get()]
        await asyncio.sleep(1.5)  # one message per burst: an utterance logs several events at once
        while not _queue.empty():
            lines.append(_queue.get_nowait())
        if not _room_id:
            continue  # nobody has opened a room with RESQ yet
        try:
            await _post(rest, agent_id, "\n".join(lines))
        except Exception as e:
            print(f"[band] feed post failed: {type(e).__name__}: {e}")


def _load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_state(**changes) -> None:
    state = {**_load_state(), **changes}
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)


async def _agent_credentials(client_for, key: str) -> Tuple[str, str]:
    """
    (agent id, agent API key). An agent key is used as it is. A user (account) key registers a "RESQ"
    agent once; BAND shows an agent's key only at registration, so it is kept in STATE_FILE.
    """
    from band.client.rest import DEFAULT_REQUEST_OPTIONS as OPTS
    from band_rest import AgentRegisterRequest
    try:
        return (await client_for(key).agent_api_identity.get_agent_me(request_options=OPTS)).data.id, key
    except Exception as e:
        if getattr(e, "status_code", None) not in (401, 403):  # BAND answers either for a user key here
            raise
    user = client_for(key)
    state = _load_state()
    mine = (await user.human_api_agents.list_my_agents(name=AGENT_NAME, request_options=OPTS)).data or []
    if state.get("agent_key") and any(a.id == state.get("agent_id") for a in mine):
        return state["agent_id"], state["agent_key"]
    for a in mine:  # a RESQ agent from an earlier run whose saved key is gone: replace it
        if a.description == AGENT_DESCRIPTION:
            await user.human_api_agents.delete_my_agent(a.id, force=True, request_options=OPTS)
    reg = (await user.human_api_agents.register_my_agent(
        agent=AgentRegisterRequest(name=AGENT_NAME, description=AGENT_DESCRIPTION), request_options=OPTS)).data
    _save_state(agent_id=reg.agent.id, agent_key=reg.credentials.api_key, room_id=None)
    print(f"[band] registered agent {AGENT_NAME} ({reg.agent.id})")
    return reg.agent.id, reg.credentials.api_key


async def _feed_room(rest, agent_id: str) -> str:
    """The room the feed goes to: the saved one, or a new "RESQ live feed" room with the agent's owner in it."""
    from band.client.rest import DEFAULT_REQUEST_OPTIONS as OPTS, chat_room_request
    from band_rest import ParticipantRequest, RenameAgentChatRequestChat
    state = _load_state()
    if state.get("room_id") and state.get("agent_id") == agent_id:
        return state["room_id"]
    owner = (await rest.agent_api_identity.get_agent_me(request_options=OPTS)).data.owner_uuid
    room_id = (await rest.agent_api_chats.create_agent_chat(chat=chat_room_request(), request_options=OPTS)).data.id
    await rest.agent_api_chats.rename_agent_chat(room_id, chat=RenameAgentChatRequestChat(title="RESQ live feed"), request_options=OPTS)
    await rest.agent_api_participants.add_agent_chat_participant(
        chat_id=room_id, participant=ParticipantRequest(participant_id=owner), request_options=OPTS)
    _save_state(agent_id=agent_id, room_id=room_id)
    return room_id


async def run() -> None:
    """Started with the server; returns immediately when BAND isn't configured."""
    global _loop, _queue
    if not enabled():
        return
    try:
        from band import Agent
        from band.client.rest import AsyncRestClient
        from band.config.settings import PlatformSettings
    except ImportError:
        print("[band] BAND keys set but band-sdk is not installed (pip install band-sdk; needs Python 3.11+)")
        return
    global _room_id, status
    status = "connecting"
    url = PlatformSettings().BAND_REST_URL
    try:
        agent_id, api_key = await _agent_credentials(lambda k: AsyncRestClient(base_url=url, api_key=k), os.getenv("BAND_API_KEY"))
        rest = AsyncRestClient(base_url=url, api_key=api_key)
        _room_id = _room_id or await _feed_room(rest, agent_id)
    except Exception as e:
        print(f"[band] could not connect: {type(e).__name__}: {getattr(e, 'body', e)}")
        status = "error"
        return
    print(f"[band] connected as agent {agent_id}; feed room {_room_id}")
    status = "connected"
    _loop, _queue = asyncio.get_running_loop(), asyncio.Queue(maxsize=500)
    db_engine.listeners.append(_on_event)
    agent = Agent.create(adapter=_adapter(), agent_id=agent_id, api_key=api_key)
    feed = asyncio.create_task(_feed(rest, agent_id))
    try:
        await agent.run(install_signal_handlers=False)  # uvicorn owns Ctrl+C
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"[band] agent stopped: {type(e).__name__}: {getattr(e, 'body', e)}")  # body, not headers
        status = "error"
    finally:
        feed.cancel()
        db_engine.listeners.remove(_on_event)
