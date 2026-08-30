import type { LocationSelection } from "../../types";

/**
 * The product's coarse United States envelope for traveler-selected endpoints.
 *
 * These bounds mirror `_supported_live_geography` in `app/api.py`, which the
 * server applies before any live provider call. The server applies them only on
 * the live path, so this client check is the only thing that stops a traveler
 * from pinning an out-of-country endpoint while replaying fixtures. It is a
 * usability guard, not a security boundary: the server stays authoritative and
 * still answers `unsupported_geography` for a live request outside the box.
 */
export const UNITED_STATES_BOUNDS = {
  minLatitude: 18,
  maxLatitude: 72,
  minLongitude: -180,
  maxLongitude: -65,
} as const;

export const OUT_OF_BOUNDS_MESSAGE =
  "Supported live-data geography is the United States. Choose a point inside the supported area.";

export function isWithinUnitedStates(point: {
  latitude: number;
  longitude: number;
}): boolean {
  return (
    point.latitude >= UNITED_STATES_BOUNDS.minLatitude &&
    point.latitude <= UNITED_STATES_BOUNDS.maxLatitude &&
    point.longitude >= UNITED_STATES_BOUNDS.minLongitude &&
    point.longitude <= UNITED_STATES_BOUNDS.maxLongitude
  );
}

/** Build the endpoint shape the trip request consumes from a raw coordinate. */
export function endpointFromCoordinates(
  latitude: number,
  longitude: number,
  { name, context }: { name: string; context: string }
): LocationSelection {
  return {
    id: `point-${latitude.toFixed(5)}-${longitude.toFixed(5)}`,
    name,
    context,
    latitude,
    longitude,
  };
}

const GEOLOCATION_MESSAGES: Record<number, string> = {
  1: "Location permission was declined. Choose the origin on the map instead.",
  2: "Your device could not determine a location. Choose the origin on the map instead.",
  3: "The location request timed out. Choose the origin on the map instead.",
};

/**
 * Resolve the traveler's current position as a trip endpoint.
 *
 * Rejects with a traveler-readable message rather than a `GeolocationPositionError`
 * so the calling screen can render the reason directly, and refuses a position
 * outside the supported geography for the same reason a map click is refused.
 */
export function requestCurrentLocation(): Promise<LocationSelection> {
  return new Promise((resolve, reject) => {
    if (!("geolocation" in navigator)) {
      reject(
        new Error(
          "This browser cannot share a location. Choose the origin on the map instead."
        )
      );
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const point = endpointFromCoordinates(
          position.coords.latitude,
          position.coords.longitude,
          { name: "Your location", context: "Shared by this device" }
        );
        if (!isWithinUnitedStates(point)) {
          reject(new Error(OUT_OF_BOUNDS_MESSAGE));
          return;
        }
        resolve(point);
      },
      (error) => {
        reject(
          new Error(
            GEOLOCATION_MESSAGES[error.code] ??
              "The location request failed. Choose the origin on the map instead."
          )
        );
      },
      { timeout: 10000, maximumAge: 60000 }
    );
  });
}
