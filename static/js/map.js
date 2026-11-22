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

        // Dark theme map tiles (CartoDB Dark Matter)
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; OpenStreetMap contributors &copy; CARTO',
            subdomains: 'abcd',
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
            this.incidentMarker.bindPopup(`
                <div style="color: #0f172a; font-family: sans-serif; font-size: 12px;">
                    <strong style="color: ${color};">INCIDENT LOCATION</strong><br>
                    <strong>Desc:</strong> ${esc(incident.description)}<br>
                    <strong>Status:</strong> ${esc(incident.verification_status)}<br>
                    <strong>Precision:</strong> ${esc(incident.precision)}
                </div>
            `);
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
    }
}

const mapController = new IncidentMapController();
