"""
RESQ 4.0 Durable Persistence Engine
Implements SQLite authoritative storage, in-memory session caching,
idempotency recording, and restart recovery state restoration.
"""
import sqlite3
import json
import os
import threading
from typing import Optional, List, Dict
from datetime import datetime

from backend.models.incident import IncidentRecord, TimelineEvent, CoordinationAction

DB_PATH = os.getenv("RESQ_DB_PATH") or os.path.join(os.path.dirname(os.path.dirname(__file__)), "resq_continuity.db")

class PersistenceEngine:
    _lock = threading.Lock()
    
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._memory_cache: Dict[str, IncidentRecord] = {}
        self._init_db()
        self.restore_cache_from_disk()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Incidents table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS incidents (
                incident_id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                category TEXT NOT NULL,
                urgency TEXT NOT NULL,
                connection_state TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                language TEXT NOT NULL,
                data_json TEXT NOT NULL
            );
            """)
            
            # Events audit log table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS timeline_events (
                event_id TEXT PRIMARY KEY,
                incident_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                actor TEXT NOT NULL,
                summary TEXT NOT NULL,
                details_json TEXT NOT NULL,
                is_failure_event INTEGER DEFAULT 0,
                FOREIGN KEY (incident_id) REFERENCES incidents(incident_id)
            );
            """)
            
            # Actions and Idempotency table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS coordination_actions (
                action_id TEXT PRIMARY KEY,
                idempotency_key TEXT UNIQUE NOT NULL,
                incident_id TEXT NOT NULL,
                action_type TEXT NOT NULL,
                target_agency TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                transmitted_at TEXT,
                acknowledged_at TEXT,
                assigned_at TEXT,
                retry_count INTEGER DEFAULT 0,
                operator_approved INTEGER DEFAULT 0,
                data_json TEXT NOT NULL,
                FOREIGN KEY (incident_id) REFERENCES incidents(incident_id)
            );
            """)
            
            conn.commit()

    def save_incident(self, incident: IncidentRecord) -> IncidentRecord:
        with self._lock:
            incident.updated_at = datetime.utcnow().isoformat()
            data_json = incident.model_dump_json()
            
            # Update cache
            self._memory_cache[incident.incident_id] = incident
            
            # Persist to disk
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT INTO incidents (incident_id, state, category, urgency, connection_state, created_at, updated_at, language, data_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(incident_id) DO UPDATE SET
                    state=excluded.state,
                    category=excluded.category,
                    urgency=excluded.urgency,
                    connection_state=excluded.connection_state,
                    updated_at=excluded.updated_at,
                    language=excluded.language,
                    data_json=excluded.data_json;
                """, (
                    incident.incident_id,
                    incident.state.value,
                    incident.category.value,
                    incident.urgency.value,
                    incident.connection_state.value,
                    incident.created_at,
                    incident.updated_at,
                    incident.language,
                    data_json
                ))
                conn.commit()
            return incident

    def get_incident(self, incident_id: str) -> Optional[IncidentRecord]:
        with self._lock:
            if incident_id in self._memory_cache:
                return self._memory_cache[incident_id]
            
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT data_json FROM incidents WHERE incident_id = ?", (incident_id,))
                row = cursor.fetchone()
                if row:
                    inc = IncidentRecord.model_validate_json(row["data_json"])
                    self._memory_cache[incident_id] = inc
                    return inc
            return None

    def list_incidents(self) -> List[IncidentRecord]:
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT data_json FROM incidents ORDER BY updated_at DESC")
                rows = cursor.fetchall()
                incidents = [IncidentRecord.model_validate_json(r["data_json"]) for r in rows]
                for inc in incidents:
                    self._memory_cache[inc.incident_id] = inc
                return incidents

    def log_event(self, event: TimelineEvent):
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT INTO timeline_events (event_id, incident_id, timestamp, event_type, actor, summary, details_json, is_failure_event)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO NOTHING;
                """, (
                    event.event_id,
                    event.incident_id,
                    event.timestamp,
                    event.event_type,
                    event.actor,
                    event.summary,
                    json.dumps(event.details),
                    1 if event.is_failure_event else 0
                ))
                conn.commit()

    def get_events(self, incident_id: str) -> List[TimelineEvent]:
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM timeline_events WHERE incident_id = ? ORDER BY timestamp ASC", (incident_id,))
                rows = cursor.fetchall()
                events = []
                for r in rows:
                    events.append(TimelineEvent(
                        event_id=r["event_id"],
                        incident_id=r["incident_id"],
                        timestamp=r["timestamp"],
                        event_type=r["event_type"],
                        actor=r["actor"],
                        summary=r["summary"],
                        details=json.loads(r["details_json"]),
                        is_failure_event=bool(r["is_failure_event"])
                    ))
                return events

    def save_action(self, action: CoordinationAction):
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT INTO coordination_actions (
                    action_id, idempotency_key, incident_id, action_type, target_agency,
                    status, created_at, transmitted_at, acknowledged_at, assigned_at,
                    retry_count, operator_approved, data_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(action_id) DO UPDATE SET
                    status=excluded.status,
                    transmitted_at=excluded.transmitted_at,
                    acknowledged_at=excluded.acknowledged_at,
                    assigned_at=excluded.assigned_at,
                    retry_count=excluded.retry_count,
                    operator_approved=excluded.operator_approved,
                    data_json=excluded.data_json;
                """, (
                    action.action_id,
                    action.idempotency_key,
                    action.incident_id,
                    action.action_type,
                    action.target_agency,
                    action.status.value,
                    action.created_at,
                    action.transmitted_at,
                    action.acknowledged_at,
                    action.assigned_at,
                    action.retry_count,
                    1 if action.operator_approved else 0,
                    action.model_dump_json()
                ))
                conn.commit()

    def get_action_by_idempotency_key(self, idempotency_key: str) -> Optional[CoordinationAction]:
        with self._lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT data_json FROM coordination_actions WHERE idempotency_key = ?", (idempotency_key,))
                row = cursor.fetchone()
                if row:
                    return CoordinationAction.model_validate_json(row["data_json"])
            return None

    def restore_cache_from_disk(self):
        """Restores in-memory session cache from durable SQLite on boot/restart."""
        with self._lock:
            self._memory_cache.clear()
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT data_json FROM incidents")
                rows = cursor.fetchall()
                for r in rows:
                    inc = IncidentRecord.model_validate_json(r["data_json"])
                    self._memory_cache[inc.incident_id] = inc

db_engine = PersistenceEngine()
