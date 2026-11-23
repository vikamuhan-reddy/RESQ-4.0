/**
 * RESQ Command Centre: queue, incident workspace, live updates and operator actions.
 * Everything from the caller, the AI or an operator goes through esc() or textContent before display.
 */

let currentIncidents = [];
let activeIncidentId = null;
let callIncidentId = null;  // the call this screen is taking; intake goes here, not to whatever is selected

const CLOSED = ['RESOLUTION_REVIEW', 'CLOSED'];
const CATEGORY_ICON = {
    'Road Accident': 'fa-car-burst', 'Medical Emergency': 'fa-heart-pulse', 'Fire Hazard': 'fa-fire',
    'Structural Collapse': 'fa-building-circle-exclamation', 'Industrial Hazard / Leak': 'fa-biohazard',
    'Criminal Incident': 'fa-user-shield', 'Flood / Natural Disaster': 'fa-house-flood-water', 'Other Emergency': 'fa-triangle-exclamation',
};
const DEPT_ICON = {
    DISPATCH_EMS: 'fa-truck-medical', NOTIFY_FIRE_RESCUE: 'fa-fire-extinguisher', ALERT_POLICE: 'fa-shield-halved',
    ALERT_TRAFFIC_POLICE: 'fa-traffic-light', HAZMAT_CONTAINMENT: 'fa-biohazard',
};
const URGENCY_CHIP = { CRITICAL: 'chip-red', HIGH: 'chip-amber', MEDIUM: 'chip-cyan', LOW: 'chip-slate', UNKNOWN: 'chip-slate' };
const STATE_LABEL = {
    RECEIVED: 'Received', INFORMATION_GATHERING: 'Gathering info', VALIDATION: 'Validating', OPERATOR_REVIEW: 'Needs review',
    ESCALATION_PENDING: 'Dispatch pending', ESCALATION_SENT: 'Dispatched', ACKNOWLEDGED: 'Acknowledged', ASSIGNED: 'Assigned',
    ACTIVE_MONITORING: 'Monitoring', RESOLUTION_REVIEW: 'Resolution review', CLOSED: 'Closed',
};
const nice = s => String(s || '').replace(/_/g, ' ').toLowerCase().replace(/^\w/, c => c.toUpperCase());
const catIcon = c => CATEGORY_ICON[c] || CATEGORY_ICON['Other Emergency'];

document.addEventListener('DOMContentLoaded', async () => {
    mapController.init();
    mapController.enablePickOnClick(confirmLocation);
    renderCallTarget();
    setupEventListeners();
    loadHealth();
    setInterval(loadHealth, 30000);
    setInterval(() => renderQueue(currentIncidents), 15000);  // keep "x min ago" fresh
    await loadIncidents();
    API.initSSE(handleRealtimeEvent);
});

// ----------------- Top bar -----------------
async function loadHealth() {
    try {
        const h = await API.get('/api/health');
        const s = h.integrations || {};
        const set = (id, on, warn, title) => {
            const el = document.getElementById(id);
            if (!el) return;
            el.className = 'svc' + (on ? ' on' : warn ? ' warn' : '');
            el.title = title;
        };
        set('svc-gemini', s.gemini, false, s.gemini ? 'Gemini understands the call (keyword rules if it is busy)' : 'No Gemini key: keyword rules only');
        set('svc-lyzr', s.lyzr, false, s.lyzr ? 'Lyzr writes the crew handover brief after each dispatch' : 'Lyzr not configured');
        set('svc-band', s.band === 'connected', s.band === 'connecting' || s.band === 'error', `BAND agent room: ${s.band || 'off'}`);
        set('svc-telegram', s.telegram, false, s.telegram ? 'Departments receive pre-alerts and dispatches on Telegram' : 'Telegram not configured: deliveries are simulated');
    } catch (err) {
        console.warn('Health check failed', err);
    }
}

function renderStats(incidents) {
    const open = incidents.filter(i => !CLOSED.includes(i.state) && !i.is_merged);
    const actions = open.flatMap(i => i.coordination_actions || []);
    const put = (id, n) => { const el = document.getElementById(id); if (el) el.textContent = n; };
    put('stat-open', open.length);
    put('stat-critical', open.filter(i => i.urgency === 'CRITICAL').length);
    put('stat-pending', actions.filter(a => a.status === 'CREATED' || a.status === 'FAILED').length);
    put('stat-sent', incidents.flatMap(i => i.coordination_actions || []).filter(a => ['SENT', 'ACKNOWLEDGED', 'ACCEPTED_OR_ASSIGNED'].includes(a.status)).length);
}

// ----------------- Call console -----------------
function fillSample(text, lang) {
    document.getElementById('voice-transcript-input').value = text;
    document.getElementById('voice-lang-select').value = lang;
    voiceInterface.setLanguage(lang);
}

function renderCallTarget() {
    const el = document.getElementById('call-target');
    if (!el) return;
    if (!callIncidentId) {
        el.innerHTML = '<span class="text-slate-500">next statement starts a new call</span>';
        return;
    }
    el.innerHTML = `<span class="chip chip-green"><span class="live-dot"></span> Live call ${esc(callIncidentId.slice(-6))}</span> <button id="btn-end-call" class="ml-1 text-rose-300 hover:text-rose-200 font-semibold">End call</button>`;
    document.getElementById('btn-end-call').onclick = () => { callIncidentId = null; renderCallTarget(); };
}

function continueCall() {
    if (!activeIncidentId) return alert('Select an incident first.');
    callIncidentId = activeIncidentId;
    renderCallTarget();
    showVoiceStatus(`New statements now go to ${activeIncidentId}.`, 'info');
}

function showVoiceStatus(message, type = 'info') {
    const el = document.getElementById('voice-status');
    if (!el) return;
    el.className = `voice-status ${type}`;
    el.textContent = message;
    clearTimeout(showVoiceStatus.timer);
    showVoiceStatus.timer = setTimeout(() => { el.textContent = ''; }, 9000);
}

function setupEventListeners() {
    const langSelect = document.getElementById('voice-lang-select');
    langSelect.addEventListener('change', e => voiceInterface.setLanguage(e.target.value));

    const recordBtn = document.getElementById('btn-record');
    recordBtn.addEventListener('click', async () => {
        const isRecording = await voiceInterface.toggleRecording(
            'waveform-canvas',
            (transcript, isFinal) => {
                const input = document.getElementById('voice-transcript-input');
                if (input && (isFinal || !input.value)) input.value = transcript;
            },
            (message, type) => showVoiceStatus(message, type)
        );
        recordBtn.innerHTML = isRecording ? '<i class="fas fa-stop"></i> Stop' : '<i class="fas fa-microphone"></i> Push to talk';
        recordBtn.classList.toggle('recording', isRecording);
    });

    const input = document.getElementById('voice-transcript-input');
    input.addEventListener('keydown', e => { if (e.key === 'Enter') document.getElementById('btn-submit-intake').click(); });

    const submitBtn = document.getElementById('btn-submit-intake');
    submitBtn.addEventListener('click', async () => {
        const lang = langSelect.value;
        if (!input.value.trim()) return showVoiceStatus("Type or record what the caller said first.", 'warn');
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i> Analysing';
        showVoiceStatus('Voice agent is reading the call…', 'info');
        try {
            // Statements go to this screen's live call, never to whichever incident happens to be selected
            if (!callIncidentId) {
                const created = await API.post('/api/incidents', { category: 'Other Emergency', language: lang });
                callIncidentId = created.incident_id;
                renderCallTarget();
            }
            const inc = await API.post(`/api/incidents/${callIncidentId}/voice-intake`, { transcript: input.value.trim(), language: lang });
            input.value = '';
            await selectIncident(callIncidentId);
            showVoiceStatus('Call analysed.', 'success');
            askCaller(inc.follow_up_queue && inc.follow_up_queue[0]);
        } catch (err) {
            showVoiceStatus('Could not analyse the call: ' + err.message, 'error');
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fas fa-bolt"></i> Analyse';
        }
    });
}

// Speak the next question to the caller; warn if this browser has no voice for the language
function askCaller(q) {
    if (!q) return;
    if (voiceInterface.speak(q.question_text, q.language)) {
        showVoiceStatus(`Asking the caller: ${q.question_text}`, 'info');
    } else {
        showVoiceStatus('No Tamil voice in this browser. Open the dashboard in Microsoft Edge, or read the question to the caller.', 'warn');
    }
}

// ----------------- Live updates -----------------
function handleRealtimeEvent(msg) {
    loadIncidents(false);
    if (activeIncidentId && msg.data && msg.data.incident_id === activeIncidentId) {
        renderIncidentDetail(msg.data);
    }
}

// Server timestamps are UTC without a "Z"; without this, browsers read them as local time
function parseUtc(s) {
    return new Date(/Z$|[+-]\d\d:\d\d$/.test(s) ? s : s + 'Z');
}

function ago(ts) {
    const s = Math.max(0, Math.round((Date.now() - parseUtc(ts)) / 1000));
    if (s < 60) return `${s}s ago`;
    if (s < 3600) return `${Math.floor(s / 60)} min ago`;
    if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
    return `${Math.floor(s / 86400)} d ago`;
}

// ----------------- Queue -----------------
async function loadIncidents(autoSelectFirst = true) {
    try {
        currentIncidents = await API.get('/api/incidents');
        renderQueue(currentIncidents);
        renderStats(currentIncidents);
        if (autoSelectFirst && currentIncidents.length && !activeIncidentId) {
            selectIncident(sortedQueue(currentIncidents)[0].incident_id);
        }
    } catch (err) {
        console.error('Failed to load incidents:', err);
    }
}

function sortedQueue(incidents) {
    const rank = i => (CLOSED.includes(i.state) || i.is_merged) ? 1 : 0;
    return [...incidents].sort((a, b) => rank(a) - rank(b) || parseUtc(b.created_at) - parseUtc(a.created_at));
}

function renderQueue(incidents) {
    const list = document.getElementById('queue-list');
    if (!list) return;
    const count = document.getElementById('queue-count');
    if (count) count.textContent = incidents.filter(i => !CLOSED.includes(i.state) && !i.is_merged).length;

    if (!incidents.length) {
        list.innerHTML = '<div class="text-center text-slate-500 text-sm py-10"><i class="fas fa-inbox text-2xl mb-2 block"></i>No calls yet.<br>Click <strong>New call</strong> to start.</div>';
        return;
    }
    list.innerHTML = sortedQueue(incidents).map(inc => {
        const loc = inc.locations.incident_location;
        const verified = loc.verification_status === 'INDEPENDENTLY_VERIFIED';
        const closed = CLOSED.includes(inc.state) || inc.is_merged;
        const depts = (inc.coordination_actions || []).map(a =>
            `<span class="dept-dot s-${esc(a.status)}" title="${esc(a.target_agency)}: ${esc(a.status)}"><i class="fas ${DEPT_ICON[a.action_type] || 'fa-building-shield'}"></i></span>`).join('');
        return `
        <div class="qcard u-${esc(inc.urgency)} ${inc.incident_id === activeIncidentId ? 'active' : ''} ${closed ? 'closed' : ''}" data-id="${esc(inc.incident_id)}">
            <div class="flex items-start gap-2.5">
                <div class="qicon"><i class="fas ${catIcon(inc.category)}"></i></div>
                <div class="flex-1 min-w-0">
                    <div class="flex items-center justify-between gap-2">
                        <span class="font-bold text-[13px] truncate">${esc(inc.category)}</span>
                        <span class="text-[10.5px] text-slate-500 shrink-0">${ago(inc.created_at)}</span>
                    </div>
                    <div class="text-[12px] text-slate-400 truncate mt-0.5">
                        <i class="fas ${verified ? 'fa-circle-check text-emerald-400' : 'fa-location-dot text-slate-500'} mr-1"></i>${esc(loc.description)}
                    </div>
                    <div class="flex flex-wrap items-center gap-1 mt-2">
                        <span class="chip ${URGENCY_CHIP[inc.urgency] || 'chip-slate'} !py-0.5 !text-[10px]">${esc(inc.urgency)}</span>
                        <span class="chip chip-slate !py-0.5 !text-[10px]">${esc(inc.is_merged ? 'Merged' : (STATE_LABEL[inc.state] || nice(inc.state)))}</span>
                        ${inc.connection_state === 'DISCONNECTED' ? '<span class="chip chip-violet !py-0.5 !text-[10px]"><i class="fas fa-phone-slash"></i> Dropped</span>' : ''}
                        <span class="flex-1"></span>${depts}
                    </div>
                </div>
            </div>
        </div>`;
    }).join('');
    list.querySelectorAll('.qcard').forEach(card => { card.onclick = () => selectIncident(card.dataset.id); });
}

async function selectIncident(incident_id) {
    activeIncidentId = incident_id;
    renderQueue(currentIncidents);
    try {
        renderIncidentDetail(await API.get(`/api/incidents/${incident_id}`));
    } catch (err) {
        console.error('Error fetching incident:', err);
    }
}

// ----------------- Incident workspace -----------------
function showWorkspace() {
    const view = document.getElementById('detail-view');
    if (!view.classList.contains('hidden')) return;
    view.classList.remove('hidden');
    document.getElementById('detail-body').classList.remove('hidden');
    document.getElementById('detail-empty').classList.add('hidden');
    // Leaflet measured the map while it was hidden; re-measure now it is visible
    setTimeout(() => mapController.map && mapController.map.invalidateSize(), 0);
}

function renderIncidentDetail(inc) {
    showWorkspace();
    const loc = inc.locations.incident_location;
    const callerLoc = inc.locations.caller_location;
    const setText = (id, t) => { const el = document.getElementById(id); if (el) el.textContent = t; };

    document.getElementById('detail-icon').innerHTML = `<i class="fas ${catIcon(inc.category)}"></i>`;
    setText('detail-category', inc.category);
    setText('detail-id', inc.incident_id);
    document.getElementById('detail-location').innerHTML = `<i class="fas fa-location-dot mr-1"></i>${esc(loc.description)}`;
    const urg = document.getElementById('detail-urgency');
    urg.textContent = inc.urgency;
    urg.className = `chip ${URGENCY_CHIP[inc.urgency] || 'chip-slate'}`;
    setText('detail-state', inc.is_merged ? `Merged into ${inc.merged_into_id}` : (STATE_LABEL[inc.state] || nice(inc.state)));
    const conn = document.getElementById('detail-conn');
    const dropped = inc.connection_state === 'DISCONNECTED';
    conn.innerHTML = dropped ? '<i class="fas fa-phone-slash"></i> Line dropped' : `<span class="live-dot"></span> ${esc(nice(inc.connection_state))}`;
    conn.className = `chip ${dropped ? 'chip-violet' : 'chip-green'}`;

    // Locations
    setText('loc-incident-desc', loc.description || 'Not specified');
    setText('loc-incident-precision', nice(loc.precision));
    const incStatus = document.getElementById('loc-incident-status');
    const verified = loc.verification_status === 'INDEPENDENTLY_VERIFIED';
    incStatus.textContent = verified ? 'Confirmed' : nice(loc.verification_status);
    incStatus.className = `chip ${verified ? 'chip-green' : 'chip-amber'}`;
    setText('loc-caller-desc', callerLoc.description || 'Not provided');
    setText('loc-caller-precision', nice(callerLoc.precision));
    setText('loc-caller-status', nice(callerLoc.verification_status));
    const sep = document.getElementById('loc-separation-badge');
    sep.classList.toggle('hidden', !inc.locations.is_separated);
    sep.title = inc.locations.separation_rationale || '';

    mapController.renderDualLocations(inc.locations);
    renderProvenanceFields(inc.fields);
    renderAgentReasoning(inc.reasoning, inc.follow_up_queue, inc);
    renderCoordinationActions(inc.coordination_actions);
    loadTimeline(inc.incident_id);
    loadConversation(inc.incident_id);
    renderDispatchTimer(inc);
}

let dispatchTimer = null;
function renderDispatchTimer(inc) {
    const el = document.getElementById('detail-timer');
    if (!el) return;
    clearInterval(dispatchTimer);
    const start = parseUtc(inc.created_at);
    const fmt = ms => { const s = Math.max(0, Math.round(ms / 1000)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; };
    const firstSent = (inc.coordination_actions || []).map(a => a.transmitted_at).filter(Boolean).map(parseUtc).sort((a, b) => a - b)[0];
    if (firstSent) {
        el.innerHTML = `<i class="fas fa-stopwatch mr-1"></i> First department notified in ${fmt(firstSent - start)}`;
        el.className = 'timer done';
        return;
    }
    const tick = () => { el.innerHTML = `<i class="fas fa-stopwatch mr-1"></i> No department notified · ${fmt(Date.now() - start)}`; };
    tick();
    dispatchTimer = setInterval(tick, 1000);
    el.className = 'timer waiting';
}

async function loadConversation(incidentId) {
    const box = document.getElementById('conversation');
    if (!box) return;
    try {
        const turns = await API.get(`/api/incidents/${incidentId}/conversation`);
        box.innerHTML = turns.length ? turns.map(t => {
            const time = parseUtc(t.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
            return t.speaker === 'caller'
                ? `<div class="flex"><div class="bubble bubble-caller"><span class="bubble-meta text-slate-400">CALLER · ${time}</span>${esc(t.text)}</div></div>`
                : `<div class="flex justify-end"><div class="bubble bubble-resq"><span class="bubble-meta text-cyan-300">RESQ ASKED · ${time}</span>${esc(t.text)}</div></div>`;
        }).join('') : '<div class="text-slate-500 text-sm italic py-2">No conversation yet. Speak or type in the call console to start.</div>';
        box.scrollTop = box.scrollHeight;
    } catch (err) {
        console.error('Failed to load conversation:', err);
    }
}

function renderProvenanceFields(fields) {
    const container = document.getElementById('fields-container');
    if (!container) return;
    container.innerHTML = '';
    const keys = Object.keys(fields);
    if (!keys.length) {
        container.innerHTML = '<div class="text-slate-500 text-sm italic py-4">Nothing extracted yet. Details appear here as the caller speaks.</div>';
        return;
    }
    // Built with DOM methods: every value here came from a caller, the AI or an operator
    const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; };
    keys.forEach(k => {
        const f = fields[k];
        const verified = f.verification_status === 'INDEPENDENTLY_VERIFIED' || f.verification_status === 'OPERATOR_VERIFIED';
        const card = el('div', 'fact');

        const head = el('div', 'flex items-center justify-between gap-2');
        head.appendChild(el('span', 'fact-name', f.field_name.replace(/_/g, ' ')));
        const badges = el('div', 'flex items-center gap-1.5');
        if (f.history.length) badges.appendChild(el('span', 'chip chip-cyan !py-0.5 !text-[10px]', `${f.history.length} edit${f.history.length > 1 ? 's' : ''}`));
        badges.appendChild(el('span', `chip ${verified ? 'chip-green' : 'chip-amber'} !py-0.5 !text-[10px]`, verified ? 'Verified' : nice(f.verification_status)));
        head.appendChild(badges);

        const value = el('div', 'fact-value', typeof f.current_value === 'object' ? JSON.stringify(f.current_value) : String(f.current_value));

        const foot = el('div', 'flex items-center justify-between gap-2 mt-2 text-[11px] text-slate-500');
        const src = el('div', 'flex items-center gap-2 min-w-0');
        src.appendChild(el('span', 'truncate', `${nice(f.source)}${f.extraction_method ? ' · ' + f.extraction_method : ''}`));
        const bar = el('span', 'conf-bar shrink-0');
        const fill = el('span');
        fill.style.width = `${Math.round((f.confidence || 0) * 100)}%`;
        bar.appendChild(fill);
        src.appendChild(bar);
        src.appendChild(el('span', 'shrink-0', `${Math.round((f.confidence || 0) * 100)}%`));
        const edit = el('button', 'text-cyan-300 hover:text-cyan-200 font-semibold shrink-0');
        edit.innerHTML = '<i class="fas fa-pen-to-square"></i> Verify';
        edit.addEventListener('click', () => promptFieldOverride(f.field_name, String(f.current_value)));
        foot.appendChild(src);
        foot.appendChild(edit);

        card.appendChild(head);
        card.appendChild(value);
        card.appendChild(foot);
        container.appendChild(card);
    });
}

function renderAgentReasoning(reasoning, followUps, inc) {
    document.getElementById('reasoning-urgency').textContent = reasoning.urgency_explanation || 'Pending triage';

    const pct = Math.round((reasoning.completeness_score || 0) * 100);
    const barColor = pct >= 75 ? '#10b981' : pct >= 40 ? '#f59e0b' : '#f43f5e';
    document.getElementById('reasoning-completeness').innerHTML = `
        <div class="flex items-center gap-3 mt-1">
            <div class="flex-1 h-2 rounded-full bg-slate-800 overflow-hidden"><div class="h-2 rounded-full" style="width:${pct}%;background:${barColor}"></div></div>
            <span class="text-sm font-bold" style="color:${barColor}">${pct}%</span>
        </div>`;

    const missing = reasoning.missing_critical_fields || [];
    document.getElementById('reasoning-missing').innerHTML = missing.length
        ? missing.map(m => `<span class="chip chip-red"><i class="fas fa-circle-exclamation"></i> ${esc(m)}</span>`).join('')
        : '<span class="text-emerald-400 text-sm"><i class="fas fa-circle-check"></i> Nothing critical missing</span>';

    const contra = reasoning.contradictions || [];
    document.getElementById('reasoning-contradictions').innerHTML = contra.length
        ? contra.map(c => `<div class="text-sm text-amber-200 rounded-lg px-3 py-2 bg-amber-500/10 border border-amber-500/30"><i class="fas fa-triangle-exclamation mr-1"></i>${esc(c)}</div>`).join('')
        : '<span class="text-slate-500 text-sm">None</span>';

    const dupEl = document.getElementById('reasoning-duplicates');
    const candidates = reasoning.related_incident_candidates || [];
    if (inc && inc.is_merged) {
        dupEl.innerHTML = `<span class="text-sm text-cyan-300">Merged into ${esc(inc.merged_into_id)}; its pending dispatches were cancelled.</span>`;
    } else if (candidates.length) {
        dupEl.innerHTML = candidates.map(c => `
            <div class="rounded-lg px-3 py-2 bg-cyan-500/5 border border-cyan-500/30 text-sm">
                <div class="flex items-center justify-between gap-2">
                    <span class="font-mono text-cyan-300 text-xs">${esc(c.incident_id)}</span>
                    <button data-merge="${esc(c.incident_id)}" class="btn btn-primary btn-small">Same emergency · merge</button>
                </div>
                <div class="text-slate-400 text-xs mt-1">${esc(c.location_description)} · ${esc(c.similarity_rationale)}</div>
            </div>`).join('');
        dupEl.querySelectorAll('[data-merge]').forEach(b => { b.onclick = () => mergeInto(b.dataset.merge); });
    } else {
        dupEl.innerHTML = '<span class="text-slate-500 text-sm">None</span>';
    }

    const recs = reasoning.operator_action_recommendations || [];
    document.getElementById('reasoning-recs').innerHTML = recs.length
        ? recs.map(r => `<li class="text-sm text-slate-300 flex gap-2"><i class="fas fa-arrow-right text-amber-300 text-[10px] mt-1.5"></i><span>${esc(r)}</span></li>`).join('')
        : '<li class="text-slate-500 text-sm">None</li>';

    const card = document.getElementById('follow-up-card');
    if (followUps && followUps.length) {
        const q = followUps[0];
        card.classList.remove('hidden');
        document.getElementById('follow-up-text').textContent = q.question_text;
        document.getElementById('follow-up-rationale').textContent = q.rationale;
        document.getElementById('btn-speak-question').onclick = () => askCaller(q);
    } else {
        card.classList.add('hidden');
    }
}

function renderCoordinationActions(actions) {
    const list = document.getElementById('coordination-actions-list');
    if (!list) return;
    if (!actions || !actions.length) {
        list.innerHTML = '<div class="text-slate-500 text-sm italic py-3">No department routed yet. RESQ proposes departments as the call is understood, or add one above.</div>';
        return;
    }
    list.innerHTML = actions.map(a => {
        const sent = ['SENT', 'ACKNOWLEDGED', 'ACCEPTED_OR_ASSIGNED'].includes(a.status);
        const acked = ['ACKNOWLEDGED', 'ACCEPTED_OR_ASSIGNED'].includes(a.status);
        const failed = a.status === 'FAILED';
        const cancelled = a.status === 'CANCELLED';
        const statusChip = { SENT: 'chip-cyan', ACKNOWLEDGED: 'chip-green', ACCEPTED_OR_ASSIGNED: 'chip-green', FAILED: 'chip-red', CANCELLED: 'chip-slate' }[a.status] || 'chip-amber';
        const statusText = { CREATED: 'Awaiting confirmation', QUEUED: 'Sending…', SENT: 'Dispatched', ACKNOWLEDGED: 'Acknowledged', FAILED: 'Delivery failed', CANCELLED: 'Cancelled' }[a.status] || nice(a.status);
        const step = (label, done, fail) => `<div class="step ${done ? 'done' : ''} ${fail ? 'fail' : ''}"><div class="step-bar"></div>${label}</div>`;
        return `
        <div class="dispatch ${cancelled ? 'opacity-50' : ''}">
            <div class="flex items-center justify-between gap-2">
                <div class="flex items-center gap-2.5 min-w-0">
                    <span class="section-icon bg-emerald-500/10 text-emerald-200"><i class="fas ${DEPT_ICON[a.action_type] || 'fa-building-shield'}"></i></span>
                    <div class="min-w-0">
                        <div class="font-bold text-sm truncate">${esc(a.target_agency)}</div>
                        <div class="text-[11px] text-slate-500">${a.operator_approved ? 'Confirmed by ' + esc(a.operator_id) : 'Proposed by Coordination Agent'}</div>
                    </div>
                </div>
                <span class="chip ${statusChip}">${esc(statusText)}</span>
            </div>
            <div class="steps">
                ${step('Proposed', true)}${step('Pre-alert', !!a.pre_alert_note)}${step('Dispatched', sent, failed)}${step('Acknowledged', acked)}
            </div>
            ${a.delivery_note ? `<div class="text-[11.5px] mt-2 ${failed ? 'text-rose-300' : 'text-slate-400'}"><i class="fas fa-circle-info mr-1"></i>${esc(a.delivery_note)}</div>`
              : a.pre_alert_note ? `<div class="text-[11.5px] mt-2 text-amber-200/80"><i class="fas fa-bell mr-1"></i>${esc(a.pre_alert_note)}</div>` : ''}
            <div data-brief="${esc(a.action_id)}" class="brief hidden"></div>
            ${(a.status === 'CREATED' || failed || a.status === 'SENT') ? `
            <div class="flex items-center justify-end gap-2 mt-3">
                ${(a.status === 'CREATED' || failed) ? `<button onclick="approveAction('${esc(a.action_id)}')" class="btn btn-confirm"><i class="fas fa-check"></i> ${failed ? 'Retry dispatch' : 'Confirm dispatch'}</button>` : ''}
                ${a.status === 'SENT' ? `<button onclick="simulateAgencyAck('${esc(a.action_id)}')" class="btn btn-ghost btn-small">Simulate department ACK</button>` : ''}
            </div>` : ''}
        </div>`;
    }).join('');
}

// Who did what: each agent has its own colour in the audit trail
function actorStyle(evt) {
    const a = evt.actor || '';
    if (evt.is_failure_event) return ['fa-bolt', 'bg-rose-500/15 text-rose-300 border-rose-500/30', 'text-rose-300'];
    if (/Lyzr/.test(a)) return ['fa-file-medical', 'bg-violet-500/15 text-violet-300 border-violet-500/30', 'text-violet-300'];
    if (/Voice/.test(a)) return ['fa-microphone-lines', 'bg-cyan-500/15 text-cyan-300 border-cyan-500/30', 'text-cyan-300'];
    if (/Reasoning/.test(a)) return ['fa-brain', 'bg-amber-500/15 text-amber-300 border-amber-500/30', 'text-amber-300'];
    if (/Coordination|Orchestration/.test(a)) return ['fa-diagram-project', 'bg-sky-500/15 text-sky-300 border-sky-500/30', 'text-sky-300'];
    if (/Dispatch/.test(a)) return ['fa-paper-plane', 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30', 'text-emerald-300'];
    if (/Continuity/.test(a)) return ['fa-shield-heart', 'bg-pink-500/15 text-pink-300 border-pink-500/30', 'text-pink-300'];
    if (/Operator/.test(a)) return ['fa-headset', 'bg-slate-400/15 text-slate-200 border-slate-400/30', 'text-slate-100'];
    return ['fa-building-shield', 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30', 'text-emerald-300'];  // a department
}

async function loadTimeline(incident_id) {
    const container = document.getElementById('timeline-container');
    if (!container) return;
    try {
        const events = await API.get(`/api/incidents/${incident_id}/timeline`);
        if (!events.length) {
            container.innerHTML = '<div class="text-slate-500 text-sm italic py-3">No activity yet.</div>';
            return;
        }
        container.innerHTML = [...events].reverse().map(evt => {
            const [icon, iconCls, actorCls] = actorStyle(evt);
            const time = parseUtc(evt.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
            return `
            <div class="tl-row">
                <div class="tl-icon ${iconCls}"><i class="fas ${icon}"></i></div>
                <div class="flex-1 min-w-0">
                    <div class="flex items-center justify-between gap-2">
                        <span class="tl-actor ${actorCls}">${esc(evt.actor)}</span>
                        <span class="text-[10px] text-slate-500 font-mono shrink-0">${time}</span>
                    </div>
                    <div class="tl-text">${esc(evt.summary)}</div>
                </div>
            </div>`;
        }).join('');

        // Show each Lyzr crew brief on its dispatch card
        events.filter(e => e.event_type === 'HANDOVER_BRIEF').forEach(e => {
            const box = document.querySelector(`[data-brief="${CSS.escape((e.details && e.details.action_id) || '')}"]`);
            if (!box) return;
            const text = e.summary.replace(/^Crew brief for [^:]+:\s*/, '');
            box.innerHTML = `<div class="text-[10.5px] font-bold uppercase tracking-wider text-violet-300 mb-1"><i class="fas fa-file-medical mr-1"></i>Crew brief · written by Lyzr agent</div>${esc(text)}`;
            box.classList.remove('hidden');
        });
    } catch (err) {
        console.error('Failed to load timeline:', err);
    }
}

// ----------------- Operator actions -----------------
async function act(fn) {
    try {
        await fn();
        await selectIncident(activeIncidentId);
    } catch (err) {
        alert('Error: ' + err.message);
    }
}

async function findLocationOnMap() {
    if (!activeIncidentId) return alert('Select an incident first.');
    try {
        const candidates = await API.get(`/api/incidents/${activeIncidentId}/location-candidates`);
        if (!candidates.length) return alert('No map match for this description. Click the map to place the incident yourself.');
        mapController.showCandidates(candidates, confirmLocation);
    } catch (err) {
        alert('Map search failed: ' + err.message);
    }
}

async function confirmLocation(lat, lon, label) {
    if (!activeIncidentId) return alert('Select an incident first.');
    await act(async () => {
        await API.post(`/api/incidents/${activeIncidentId}/confirm-location`, { lat, lon, label, operator_id: 'Operator-Lead' });
        mapController.clearCandidates();
    });
}

async function mergeInto(targetId) {
    if (!activeIncidentId) return;
    if (!confirm(`Is this the same emergency as ${targetId}?\nThis report will be merged into it and its pending dispatches cancelled.`)) return;
    await act(() => API.post(`/api/incidents/${activeIncidentId}/merge-into`, { target_id: targetId, operator_id: 'Operator-Lead' }));
}

async function acknowledgeCurrentIncident() {
    if (!activeIncidentId) return;
    await act(() => API.post(`/api/incidents/${activeIncidentId}/acknowledge`, { operator_id: 'Operator-Lead' }));
}

async function promptFieldOverride(fieldName, currentValue) {
    if (!activeIncidentId) return;
    const newVal = prompt(`Verified value for '${fieldName.replace(/_/g, ' ')}':`, currentValue);
    if (!newVal || newVal === currentValue) return;
    const reason = prompt('Reason (kept in the audit trail):', 'Confirmed with the caller');
    if (!reason) return;
    await act(() => API.post(`/api/incidents/${activeIncidentId}/override-field`, { field_name: fieldName, new_value: newVal, reason, operator_id: 'Operator-Lead' }));
}

async function approveAction(actionId) {
    if (!activeIncidentId) return;
    await act(() => API.post(`/api/incidents/${activeIncidentId}/approve-action`, { action_id: actionId, operator_id: 'Operator-Lead' }));
}

async function simulateAgencyAck(actionId) {
    if (!activeIncidentId) return;
    await act(() => API.post(`/api/incidents/${activeIncidentId}/simulate-ack`, { action_id: actionId, responder_ref: 'EMS-ALS-UNIT-108' }));
}

async function proposeAction(actionType, targetAgency) {
    if (!activeIncidentId) return alert('Select an incident first.');
    await act(() => API.post(`/api/incidents/${activeIncidentId}/propose-action`, { action_type: actionType, target_agency: targetAgency }));
}

async function simulateCallerDisconnect() {
    if (!activeIncidentId) return alert('Select an incident first.');
    await act(() => API.post(`/api/incidents/${activeIncidentId}/disconnect`, { reason: 'Abrupt line drop / tower cell handover loss' }));
}

async function createNewIncident(category = 'Other Emergency', lang = null) {
    lang = lang || document.getElementById('voice-lang-select').value;
    try {
        const inc = await API.post('/api/incidents', { category, language: lang });
        callIncidentId = inc.incident_id;  // a new incident is a new call
        renderCallTarget();
        await loadIncidents(false);
        await selectIncident(inc.incident_id);
        document.getElementById('voice-transcript-input').focus();
        showVoiceStatus('New call started. Speak or type what the caller says.', 'info');
    } catch (err) {
        alert('Error creating incident: ' + err.message);
    }
}
