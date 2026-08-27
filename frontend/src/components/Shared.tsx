import { AlertCircle, Database, MapPin, RefreshCw, Search } from "lucide-react";
import { useMemo, useState } from "react";
import {
  CircleMarker,
  MapContainer,
  TileLayer,
  useMapEvents,
} from "react-leaflet";
import { dataClient } from "../services/dataClient";
import type { LocationSelection, Provenance } from "../types";

function MapClick({
  onSelect,
}: {
  onSelect: (location: LocationSelection) => void;
}) {
  useMapEvents({
    click(event) {
      onSelect({
        id: `map-${event.latlng.lat.toFixed(4)}-${event.latlng.lng.toFixed(4)}`,
        name: `Map selection ${event.latlng.lat.toFixed(3)}, ${event.latlng.lng.toFixed(3)}`,
        context: "Selected directly on the map",
        latitude: event.latlng.lat,
        longitude: event.latlng.lng,
      });
    },
  });
  return null;
}

export function LocationPicker({
  title,
  description,
  onContinue,
}: {
  title: string;
  description: string;
  onContinue: (location: LocationSelection) => void;
}) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<LocationSelection | null>(null);
  const results = useMemo(() => dataClient.searchLocations(query), [query]);
  const center: [number, number] = selected
    ? [selected.latitude, selected.longitude]
    : [29.8, -95.5];
  return (
    <section className="screen picker-screen">
      <div className="screen-heading">
        <span className="step-label">Choose a place</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      <div className="picker-layout">
        <div className="search-panel">
          <label htmlFor="location-search">Search mock locations</label>
          <div className="search-input">
            <Search size={18} />
            <input
              id="location-search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search for a landmark or area"
              autoComplete="off"
            />
          </div>
          <div
            className="suggestions"
            role="listbox"
            aria-label="Location suggestions"
          >
            {results.map((location) => (
              <button
                key={location.id}
                type="button"
                role="option"
                aria-selected={selected?.id === location.id}
                onClick={() => setSelected(location)}
              >
                <MapPin size={17} />
                <span>
                  <strong>{location.name}</strong>
                  <small>{location.context}</small>
                </span>
              </button>
            ))}
          </div>
          {results.length === 0 && (
            <p className="empty-search">
              No mock location matches that search.
            </p>
          )}
        </div>
        <div className="map-panel">
          <MapContainer
            key={`${center[0]}-${center[1]}`}
            center={center}
            zoom={selected ? 14 : 4}
            scrollWheelZoom
            className="map"
          >
            <TileLayer
              attribution="&copy; OpenStreetMap contributors"
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            <MapClick onSelect={setSelected} />
            {selected && (
              <CircleMarker
                center={[selected.latitude, selected.longitude]}
                radius={9}
                pathOptions={{
                  color: "#b9472f",
                  fillColor: "#f26b45",
                  fillOpacity: 1,
                }}
              />
            )}
          </MapContainer>
          <span className="map-hint">
            Click anywhere on the map to set a custom point.
          </span>
        </div>
      </div>
      <div className="selection-bar">
        <div>
          {selected ? (
            <>
              <span>Selected</span>
              <strong>{selected.name}</strong>
              <small>{selected.context}</small>
            </>
          ) : (
            <>
              <span>No place selected</span>
              <strong>Search or click the map to continue</strong>
            </>
          )}
        </div>
        <button
          type="button"
          disabled={!selected}
          onClick={() => selected && onContinue(selected)}
        >
          Continue
        </button>
      </div>
    </section>
  );
}

export function ProvenanceFooter({ value }: { value: Provenance }) {
  return (
    <footer className="provenance">
      <Database size={18} />
      <div>
        <strong>Data provenance</strong>
        <dl>
          <div>
            <dt>Source</dt>
            <dd>{value.source}</dd>
          </div>
          <div>
            <dt>Data date</dt>
            <dd>{value.dataDate}</dd>
          </div>
          {value.confidence && (
            <div>
              <dt>Confidence</dt>
              <dd>{value.confidence}</dd>
            </div>
          )}
          {value.coverage && (
            <div>
              <dt>Coverage</dt>
              <dd>{value.coverage}</dd>
            </div>
          )}
        </dl>
        {value.note && <p>{value.note}</p>}
      </div>
    </footer>
  );
}
export function ResultSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div
      className="skeleton-wrap"
      aria-live="polite"
      aria-label="Loading results"
    >
      <div className="skeleton skeleton-title" />
      {Array.from({ length: rows }).map((_, index) => (
        <div className="skeleton skeleton-card" key={index} />
      ))}
    </div>
  );
}
export function ResultProblem({
  kind,
  onRetry,
}: {
  kind: "empty" | "error";
  onRetry: () => void;
}) {
  return (
    <section className="problem-state">
      <AlertCircle size={30} />
      <h2>
        {kind === "empty"
          ? "No demonstration data is available"
          : "We could not load this result"}
      </h2>
      <p>
        {kind === "empty"
          ? "Choose another mock location or preview state and try again."
          : "The local data request did not complete. Your selection has been kept."}
      </p>
      <button type="button" onClick={onRetry}>
        <RefreshCw size={17} /> Retry
      </button>
    </section>
  );
}
export function DegradedNotice({ children }: { children: string }) {
  return (
    <div className="degraded-notice" role="status">
      <AlertCircle size={19} />
      <div>
        <strong>Limited result</strong>
        <span>{children}</span>
      </div>
    </div>
  );
}
