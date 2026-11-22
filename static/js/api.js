/**
 * RESQ 4.0 API Client & Real-time EventSource (SSE) Listener
 */

// Escape caller/AI/operator text before putting it into innerHTML templates
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

async function failWithDetail(res) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP error ${res.status}`);
}

const API = {
    baseUrl: '',

    async get(endpoint) {
        try {
            const res = await fetch(`${this.baseUrl}${endpoint}`);
            if (!res.ok) await failWithDetail(res);
            return await res.json();
        } catch (err) {
            console.error(`API GET ${endpoint} error:`, err);
            throw err;
        }
    },

    async post(endpoint, data = {}) {
        try {
            const res = await fetch(`${this.baseUrl}${endpoint}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            });
            if (!res.ok) await failWithDetail(res);
            return await res.json();
        } catch (err) {
            console.error(`API POST ${endpoint} error:`, err);
            throw err;
        }
    },

    // SSE Real-time Subscription
    initSSE(onEventReceived) {
        if (!window.EventSource) {
            console.warn('EventSource not supported by browser.');
            return;
        }
        const sse = new EventSource('/api/events/stream');
        sse.onmessage = (event) => {
            try {
                const parsed = JSON.parse(event.data);
                if (onEventReceived) onEventReceived(parsed);
            } catch (e) {
                console.error('Error parsing SSE event:', e);
            }
        };
        sse.onerror = (err) => {
            console.warn('SSE connection disrupted, browser will reconnect...', err);
        };
        return sse;
    }
};
