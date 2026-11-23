/**
 * RESQ 4.0 Dual-Location Interactive Map Controller
 * Integrates Leaflet to render Caller Location, Incident Location,
 * Uncertainty Radius, and separation vectors.
 */
class IncidentMapController {
    constructor(elementId = 'incident-map') {
        this.elementId = elementId;
        this.map = null;
        this.callerMarker = null;
        this.incidentMarker = null;
        this.uncertaintyCircle = null;
        this.separationLine = null;
    }

    init() {
        if (!document.getElementById(this.elementId)) return;
        if (this.map) return;

        // Default center: Chennai Anna Flyover (13.0524, 80.2508)
        this.map = L.map(this.elementId).setView([13.0524, 80.2508], 13);

        // OpenStreetMap tiles (no key needed); style.css darkens them to match the dashboard
        L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; OpenStreetMap contributors',
            maxZoom: 19
        }).addTo(this.map);
    }

    renderDualLocations(locations) {
        if (!this.map) this.init();
        if (!this.map || !locations) return;

        const caller = locations.caller_location;
        const incident = locations.incident_location;

        // Clear existing markers
        if (this.callerMarker) this.map.removeLayer(this.callerMarker);
        if (this.incidentMarker) this.map.removeLayer(this.incidentMarker);
        if (this.uncertaintyCircle) this.map.removeLayer(this.uncertaintyCircle);
        if (this.separationLine) this.map.removeLayer(this.separationLine);
        this.callerMarker = this.incidentMarker = this.uncertaintyCircle = this.separationLine = null;  // no stale references

        const bounds = [];

        // 1. Caller Location Marker (Cyan / Blue)
        if (caller && caller.latitude && caller.longitude) {
            const callerIcon = L.divIcon({
                className: 'custom-map-icon',
                html: `<div style="background-color: #06b6d4; width: 18px; height: 18px; border-radius: 50%; border: 3px solid #ffffff; box-shadow: 0 0 10px #06b6d4;"></div>`,
                iconSize: [18, 18],
                iconAnchor: [9, 9]
            });
            this.callerMarker = L.marker([caller.latitude, caller.longitude], { icon: callerIcon }).addTo(this.map);
            this.callerMarker.bindPopup(`
                <div style="color: #0f172a; font-family: sans-serif; font-size: 12px;">
                    <strong style="color: #0891b2;">CALLER LOCATION</strong><br>
                    <strong>Desc:</strong> ${esc(caller.description)}<br>
                    <strong>Status:</strong> ${esc(caller.verification_status)}<br>
                    <strong>Precision:</strong> ${esc(caller.precision)}
                </div>
            `);
            bounds.push([caller.latitude, caller.longitude]);
        }

        // 2. Incident Location Marker (Red / Amber)
        if (incident && incident.latitude && incident.longitude) {
            const isUncertain = incident.verification_status === 'UNCERTAIN';
            const color = isUncertain ? '#f59e0b' : '#ef4444';
            
            const incidentIcon = L.divIcon({
                className: 'custom-map-icon',
                html: `<div style="background-color: ${color}; width: 22px; height: 22px; border-radius: 50%; border: 3px solid #ffffff; box-shadow: 0 0 14px ${color};"></div>`,
                iconSize: [22, 22],
                iconAnchor: [11, 11]
            });
            this.incidentMarker = L.marker([incident.latitude, incident.longitude], { icon: incidentIcon }).addTo(this.map);
            if (isUncertain && this.onConfirm) {
                // Suggested by map search: one click confirms it
                this.incidentMarker.bindPopup(this._confirmPopup(`SUGGESTED, not confirmed: ${incident.description}`,
                    () => this.onConfirm(incident.latitude, incident.longitude, incident.description)));
            } else {
                this.incidentMarker.bindPopup(`
                    <div style="color: #0f172a; font-family: sans-serif; font-size: 12px;">
                        <strong style="color: ${color};">INCIDENT LOCATION</strong><br>
                        <strong>Desc:</strong> ${esc(incident.description)}<br>
                        <strong>Status:</strong> ${esc(incident.verification_status)}<br>
                        <strong>Precision:</strong> ${esc(incident.precision)}
                    </div>
                `);
            }
            bounds.push([incident.latitude, incident.longitude]);

            // Draw uncertainty radius circle if status is UNCERTAIN
            if (isUncertain) {
                this.uncertaintyCircle = L.circle([incident.latitude, incident.longitude], {
                    color: '#f59e0b',
                    fillColor: '#f59e0b',
                    fillOpacity: 0.15,
                    radius: 750 // 750 meters landmark uncertainty radius
                }).addTo(this.map);
            }
        }

        // 3. Separation Vector line if caller is separated
        if (locations.is_separated && bounds.length >= 2) {
            this.separationLine = L.polyline(bounds, {
                color: '#06b6d4',
                weight: 2,
                dashArray: '6, 8',
                opacity: 0.8
            }).addTo(this.map);
        }

        if (bounds.length > 0) {
            this.map.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 });
        }

        // Say why there is no pin, instead of leaving an empty map
        const notice = document.getElementById('map-notice');
        if (notice && incident) {
            const pinned = incident.latitude && incident.longitude;
            const verified = incident.verification_status === 'INDEPENDENTLY_VERIFIED';
            notice.classList.toggle('hidden', pinned && verified);
            notice.textContent = !pinned
                ? `No pin yet: "${incident.description}" is the caller's description. Use "Find on map" or click the map.`
                : `Amber pin = SUGGESTED by map search for "${incident.description}", not confirmed. Click it to confirm, or click the right spot.`;
        }
    }

    // Grey candidate markers from the map search; each popup has a Confirm button
    showCandidates(candidates, onConfirm) {
        this.clearCandidates();
        this.candidateLayer = L.layerGroup().addTo(this.map);
        candidates.forEach(c => {
            L.circleMarker([c.lat, c.lon], { radius: 9, color: '#94a3b8', weight: 2, fillOpacity: 0.5 })
                .bindPopup(this._confirmPopup(c.name, () => onConfirm(c.lat, c.lon, c.name)))
                .addTo(this.candidateLayer);
        });
        this.map.fitBounds(candidates.map(c => [c.lat, c.lon]), { padding: [40, 40], maxZoom: 16 });
    }

    clearCandidates() {
        if (this.candidateLayer) this.map.removeLayer(this.candidateLayer);
        this.candidateLayer = null;
    }

    // Clicking anywhere on the map offers to confirm that exact point
    enablePickOnClick(onConfirm) {
        if (!this.map) return;
        this.onConfirm = onConfirm;  // also used by the suggested pin's popup
        this.map.on('click', (e) => {
            const label = `${e.latlng.lat.toFixed(5)}, ${e.latlng.lng.toFixed(5)}`;
            L.popup().setLatLng(e.latlng)
                .setContent(this._confirmPopup(label, () => onConfirm(e.latlng.lat, e.latlng.lng, null)))
                .openOn(this.map);
        });
    }

    _confirmPopup(label, onConfirm) {
        const box = document.createElement('div');
        box.style.cssText = 'color:#0f172a;font-family:sans-serif;font-size:12px;max-width:230px';
        const text = document.createElement('div');
        text.textContent = label;
        const btn = document.createElement('button');
        btn.textContent = 'Confirm incident location here';
        btn.style.cssText = 'margin-top:6px;padding:4px 8px;background:#059669;color:#fff;border-radius:4px;font-weight:600;cursor:pointer';
        btn.onclick = () => { this.map.closePopup(); onConfirm(); };
        box.append(text, btn);
        return box;
    }
}

const mapController = new IncidentMapController();
