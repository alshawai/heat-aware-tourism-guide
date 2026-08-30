import { Crosshair, MapPin } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  CircleMarker,
  MapContainer,
  TileLayer,
  Tooltip,
  useMapEvents,
} from "react-leaflet";
import { dataClient } from "../../services/dataClient";
import type { LocationSelection } from "../../types";
import {
  OUT_OF_BOUNDS_MESSAGE,
  endpointFromCoordinates,
  isWithinUnitedStates,
  requestCurrentLocation,
} from "./geography";

export type EndpointRole = "origin" | "destination";

function MapClick({
  onSelect,
}: {
  onSelect: (point: LocationSelection) => void;
}) {
  useMapEvents({
    click(event) {
      onSelect(
        endpointFromCoordinates(event.latlng.lat, event.latlng.lng, {
          name: `Map point ${event.latlng.lat.toFixed(3)}, ${event.latlng.lng.toFixed(3)}`,
          context: "Selected directly on the map",
        })
      );
    },
  });
  return null;
}

/**
 * Pick both trip endpoints by geolocation, place search, or map click.
 *
 * Every candidate passes the client United States check before it reaches the
 * setup, because the server applies its live-geography envelope only on the live
 * path and a billable analysis should not be spent learning that.
 */
export function EndpointPicker({
  origin,
  destination,
  onChange,
  disabled = false,
  error,
}: {
  origin: LocationSelection;
  destination: LocationSelection;
  onChange: (role: EndpointRole, point: LocationSelection) => void;
  disabled?: boolean;
  error?: string;
}) {
  const [role, setRole] = useState<EndpointRole>("origin");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<LocationSelection[]>([]);
  const [searchState, setSearchState] = useState<"idle" | "loading" | "error">(
    "idle"
  );
  const [notice, setNotice] = useState("");
  const [locating, setLocating] = useState(false);
  const searchRef = useRef<AbortController | null>(null);
  // The initial view only; Leaflet keeps its own centre once the traveler pans.
  const initialCenter = useRef<[number, number]>([
    (origin.latitude + destination.latitude) / 2,
    (origin.longitude + destination.longitude) / 2,
  ]);

  useEffect(() => () => searchRef.current?.abort(), []);

  function select(point: LocationSelection) {
    if (!isWithinUnitedStates(point)) {
      setNotice(OUT_OF_BOUNDS_MESSAGE);
      return;
    }
    setNotice("");
    onChange(role, point);
  }

  // Place search is free, so it is safe to abort superseded keystrokes.
  async function search(value: string) {
    setQuery(value);
    searchRef.current?.abort();
    if (value.trim().length < 2) {
      setResults([]);
      setSearchState("idle");
      return;
    }
    const controller = new AbortController();
    searchRef.current = controller;
    setSearchState("loading");
    try {
      const response = await dataClient.searchPlaces(value, controller.signal);
      setResults(response.places);
      setSearchState("idle");
    } catch (failure) {
      if (failure instanceof DOMException && failure.name === "AbortError") {
        return;
      }
      setSearchState("error");
      setResults([]);
    }
  }

  async function useDeviceLocation() {
    setLocating(true);
    setNotice("");
    try {
      onChange("origin", await requestCurrentLocation());
      setRole("destination");
    } catch (failure) {
      setNotice(
        failure instanceof Error ? failure.message : "Location failed."
      );
    } finally {
      setLocating(false);
    }
  }

  return (
    <div className="exploratory-endpoints">
      <p>
        Set the origin and destination by sharing your location, searching, or
        clicking the map.
      </p>
      <div
        className="endpoint-buttons"
        role="group"
        aria-label="Active endpoint"
      >
        <button
          id="endpoint-origin"
          type="button"
          aria-pressed={role === "origin"}
          className={role === "origin" ? "active" : ""}
          onClick={() => setRole("origin")}
          disabled={disabled}
        >
          <MapPin size={15} /> Origin: {origin.name}
        </button>
        <button
          type="button"
          aria-pressed={role === "destination"}
          className={role === "destination" ? "active" : ""}
          onClick={() => setRole("destination")}
          disabled={disabled}
        >
          <MapPin size={15} /> Destination: {destination.name}
        </button>
      </div>
      <button
        type="button"
        className="secondary-button"
        onClick={() => void useDeviceLocation()}
        disabled={disabled || locating}
      >
        <Crosshair size={15} />{" "}
        {locating ? "Locating..." : "Use my current location as origin"}
      </button>
      <label htmlFor="place-search">Search places</label>
      <input
        id="place-search"
        value={query}
        onChange={(event) => void search(event.target.value)}
        placeholder="Search a place"
        autoComplete="off"
        disabled={disabled}
      />
      {searchState === "loading" && <p role="status">Searching places...</p>}
      {searchState === "error" && (
        <p role="alert">
          Place search is unavailable. Select the endpoint on the map.
        </p>
      )}
      {results.length > 0 && (
        <div
          className="place-results"
          role="listbox"
          aria-label="Place results"
        >
          {results.map((place) => (
            <button
              type="button"
              role="option"
              aria-selected={false}
              key={place.id}
              disabled={disabled}
              onClick={() => {
                select(place);
                setQuery("");
                setResults([]);
              }}
            >
              {place.name} <small>{place.context}</small>
            </button>
          ))}
        </div>
      )}
      {notice && (
        <p className="field-error" role="alert">
          {notice}
        </p>
      )}
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
      <MapContainer
        center={initialCenter.current}
        zoom={14}
        className="map"
        scrollWheelZoom
      >
        <TileLayer
          attribution="&copy; OpenStreetMap contributors"
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <MapClick onSelect={select} />
        <CircleMarker
          center={[origin.latitude, origin.longitude]}
          radius={8}
          pathOptions={{
            color: "#b9472f",
            fillColor: "#f26b45",
            fillOpacity: 1,
          }}
        >
          <Tooltip>Origin: {origin.name}</Tooltip>
        </CircleMarker>
        <CircleMarker
          center={[destination.latitude, destination.longitude]}
          radius={8}
          pathOptions={{
            color: "#245c4a",
            fillColor: "#237064",
            fillOpacity: 1,
          }}
        >
          <Tooltip>Destination: {destination.name}</Tooltip>
        </CircleMarker>
      </MapContainer>
      <span className="map-hint">
        Clicking the map moves the {role} pin. Live provider data is supported
        only for United States endpoints.
      </span>
    </div>
  );
}
