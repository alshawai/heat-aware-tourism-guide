import { MapContainer, Polyline, TileLayer, Tooltip } from "react-leaflet";
import type { RouteComparisonResult } from "../../types";
import { formatDistanceAndDuration, leafletPoint } from "./format";

const ALTERNATIVE_COLORS = ["#237064", "#cf922d", "#67727a"];
const SELECTED_COLOR = "#b9472f";

/**
 * The returned route alternatives drawn together, with the selected route
 * highlighted. Only routes the provider actually returned are drawn; nothing is
 * interpolated to fill a gap in the geometry.
 */
export function RouteMap({
  routes,
  selectedId,
  onSelect,
}: {
  routes: RouteComparisonResult;
  selectedId: string;
  onSelect: (identity: string) => void;
}) {
  const drawable = routes.alternatives.filter(
    (route) => (route.geometry?.length ?? 0) > 1
  );
  const center = leafletPoint(
    drawable.find((route) => route.identity === selectedId)?.geometry?.[0] ??
      drawable[0]?.geometry?.[0] ?? [-98.486, 29.425]
  );

  return (
    <div className="route-map">
      <MapContainer center={center} zoom={15} scrollWheelZoom className="map">
        <TileLayer
          attribution="&copy; OpenStreetMap contributors"
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {drawable.map((route, index) => {
          const active = route.identity === selectedId;
          return (
            <Polyline
              key={route.identity}
              positions={(route.geometry ?? []).map(leafletPoint)}
              pathOptions={{
                color: active
                  ? SELECTED_COLOR
                  : ALTERNATIVE_COLORS[index % ALTERNATIVE_COLORS.length],
                weight: active ? 7 : 4,
                opacity: active ? 1 : 0.72,
              }}
              eventHandlers={{ click: () => onSelect(route.identity) }}
            >
              <Tooltip sticky>
                {route.identity} · {formatDistanceAndDuration(route)}
              </Tooltip>
            </Polyline>
          );
        })}
      </MapContainer>
      {drawable.length === 0 && (
        <p className="map-hint" role="status">
          No route geometry was returned, so the walking routes cannot be drawn.
        </p>
      )}
    </div>
  );
}
