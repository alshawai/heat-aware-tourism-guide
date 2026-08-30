import type { LocationSelection } from "../../types";

/**
 * The trips fixture replay can answer, exactly as they were acquired.
 *
 * Four scenarios are committed (`fixtures/trips/*.trip.acquisition.json`), each
 * acquired for its own date and window, and `_fixture_matches`
 * (`app/services/trip_adapters.py`) matches a request against all of it: both
 * coordinate pairs, the date, the window, the landmark, and the district. A
 * fixture run therefore has to submit the acquired facts rather than whatever the
 * traveler typed — the alternative is `scenario_unavailable` on every fixture
 * trip, which is exactly what CI, the public demonstration, and the fixture
 * end-to-end run depend on not happening.
 *
 * Endpoints are matched on coordinates, not ids: a searched place carries a
 * provider id and a map click carries a coordinate id, so the same corner is
 * reachable under either. The tolerance mirrors the server's `abs_tol=1e-7`.
 */
export type FixtureScenario = {
  date: string;
  startHour: number;
  endHour: number;
  landmarkName: string;
  districtName: string;
};

type CatalogEntry = FixtureScenario & {
  origin: readonly [number, number];
  destination: readonly [number, number];
};

const COORDINATE_TOLERANCE = 1e-7;
const DISTRICT = "Downtown San Antonio";

const CANONICAL_ENTRY: CatalogEntry = {
  origin: [29.4245914, -98.4864288],
  destination: [29.425833, -98.485833],
  date: "2024-07-15",
  startHour: 8,
  endHour: 20,
  landmarkName: "The Alamo",
  districtName: DISTRICT,
};

const SCENARIOS: readonly CatalogEntry[] = [
  CANONICAL_ENTRY,
  {
    origin: [29.4245773, -98.4935063],
    destination: [29.4254009, -98.4994785],
    date: "2024-07-15",
    startHour: 10,
    endHour: 17,
    landmarkName: "Historic Market Square (El Mercado)",
    districtName: DISTRICT,
  },
  {
    origin: [29.424559, -98.4942042],
    destination: [29.4248225, -98.4959872],
    date: "2024-07-15",
    startHour: 10,
    endHour: 17,
    landmarkName: "Spanish Governor's Palace",
    districtName: DISTRICT,
  },
  {
    origin: [29.4228983, -98.4888465],
    destination: [29.4190825, -98.4835734],
    date: "2024-07-15",
    startHour: 10,
    endHour: 17,
    landmarkName: "Tower of the Americas",
    districtName: DISTRICT,
  },
];

function samePoint(
  place: LocationSelection,
  [latitude, longitude]: readonly [number, number]
) {
  return (
    Math.abs(place.latitude - latitude) <= COORDINATE_TOLERANCE &&
    Math.abs(place.longitude - longitude) <= COORDINATE_TOLERANCE
  );
}

function scenarioOf({
  date,
  startHour,
  endHour,
  landmarkName,
  districtName,
}: CatalogEntry): FixtureScenario {
  return { date, startHour, endHour, landmarkName, districtName };
}

/** The canonical Menger Hotel to The Alamo walk, as it was acquired. */
export const CANONICAL_FIXTURE_SCENARIO = scenarioOf(CANONICAL_ENTRY);

/** The acquired scenario for a pair of endpoints, when one was acquired. */
export function fixtureScenarioFor(
  origin: LocationSelection,
  destination: LocationSelection
): FixtureScenario | undefined {
  const match = SCENARIOS.find(
    (scenario) =>
      samePoint(origin, scenario.origin) &&
      samePoint(destination, scenario.destination)
  );
  return match ? scenarioOf(match) : undefined;
}
