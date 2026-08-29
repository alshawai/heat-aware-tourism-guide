import type {
  HotelComponentName,
  HotelRankResponse,
  HotelRankingHotel,
  LocationSelection,
  MockMode,
  RequestOptions,
  TripResponse,
} from "../types";

const locations: LocationSelection[] = [
  {
    id: "harbor",
    name: "Harbor Arts Quarter",
    context: "Historic waterfront district",
    latitude: 29.4241,
    longitude: -98.4936,
  },
  {
    id: "civic",
    name: "Civic Market Square",
    context: "Central public square",
    latitude: 30.2672,
    longitude: -97.7431,
  },
  {
    id: "garden",
    name: "Garden Museum Walk",
    context: "Museum and garden district",
    latitude: 29.9511,
    longitude: -90.0715,
  },
];

const makeTrip = (
  location: LocationSelection,
  date: string,
  limited = false
): TripResponse => ({
  location,
  date,
  metric: {
    label: limited ? "Provider temperature metric" : "NOAA Heat Index",
    unit: "C",
    actualHeatIndex: !limited,
  },
  hourly: ["07:00", "09:00", "11:00", "13:00", "15:00", "17:00", "19:00"].map(
    (hour, index) => ({
      hour,
      value: [27, 29, 33, 37, 39, 35, 31][index],
      comfort:
        index < 2 || index === 6 ? "lower" : index < 5 ? "moderate" : "higher",
    })
  ),
  recommendation: {
    window: "07:00–09:00",
    reason:
      "The selected metric is lowest in this window among the returned hourly observations.",
  },
  routes: limited
    ? [
        {
          id: "route-1",
          name: "Direct path",
          distanceMeters: 980,
          durationMinutes: 13,
          heatStatus: "Moderate exposure",
          shadePercent: 18,
          geometry: [
            [location.latitude, location.longitude],
            [location.latitude + 0.004, location.longitude + 0.006],
          ],
          steps: [
            "Head toward the selected destination",
            "Continue along the main pedestrian corridor",
            "Arrive at the selected location",
          ],
        },
      ]
    : [
        {
          id: "route-1",
          name: "Shortest returned route",
          distanceMeters: 980,
          durationMinutes: 13,
          heatStatus: "Higher exposure",
          shadePercent: 22,
          geometry: [
            [location.latitude, location.longitude],
            [location.latitude + 0.004, location.longitude + 0.006],
          ],
          steps: [
            "Head toward the selected destination",
            "Continue along the main pedestrian corridor",
            "Arrive at the selected location",
          ],
        },
        {
          id: "route-2",
          name: "More shaded returned route",
          distanceMeters: 1180,
          durationMinutes: 16,
          heatStatus: "Lower exposure",
          shadePercent: 51,
          geometry: [
            [location.latitude, location.longitude],
            [location.latitude + 0.002, location.longitude + 0.004],
            [location.latitude + 0.004, location.longitude + 0.006],
          ],
          steps: [
            "Head toward the shaded corridor",
            "Turn onto the tree-lined pedestrian way",
            "Arrive at the selected location",
          ],
        },
        {
          id: "route-3",
          name: "Market-side returned route",
          distanceMeters: 1320,
          durationMinutes: 18,
          heatStatus: "Moderate exposure",
          shadePercent: 38,
          geometry: [
            [location.latitude, location.longitude],
            [location.latitude + 0.005, location.longitude + 0.002],
            [location.latitude + 0.004, location.longitude + 0.006],
          ],
          steps: [
            "Follow the market-side walkway",
            "Cross the central plaza",
            "Arrive at the selected location",
          ],
        },
      ],
  provenance: {
    bestTime: {
      source: "mock",
      dataDate: date,
      confidence: limited ? "Moderate" : "High",
      note: "Hourly fixture observations",
    },
    routes: {
      source: "mock",
      dataDate: date,
      confidence: limited ? "Low" : "High",
      coverage: limited
        ? "Building-height coverage: 42%"
        : "Building-height coverage: 91%",
      note: "Shade is a modeled estimate based on building data.",
    },
  },
});

const makeHotels = (
  location: LocationSelection,
  few = false
): HotelRankResponse => {
  const names = [
    "Canopy House",
    "Civic Lantern",
    "Riverstone Rooms",
    "Juniper Court",
    "The Meridian",
    "Market House",
  ];
  const componentValues: Record<HotelComponentName, number[]> = {
    night: few ? [27, 27, 31] : [25, 27, 29, 31, 33, 35],
    hot_hours: few ? [5, 5, 8] : [9, 8, 7, 6, 5, 4],
    persistence: few ? [3, 3, 5] : [6, 5, 4, 3, 2, 1],
    day: few ? [38, 38, 41] : [34, 35, 36, 37, 38, 39],
  };
  const count = few ? 3 : 6;
  const components = Object.fromEntries(
    (["night", "hot_hours", "persistence", "day"] as const).map((component) => [
      component,
      {
        component,
        available: true,
        unit: component === "night" || component === "day" ? "C" : "hours",
        threshold_celsius:
          component === "hot_hours" || component === "persistence" ? 35 : null,
        provenance: "district fixture analysis",
        coverage: few ? 0.72 : 0.94,
        confidence: few ? "limited" : "limited",
        caveats: ["Candidate-relative evidence; not an absolute heat score."],
        missing_reason: null,
      },
    ])
  ) as HotelRankResponse["components"];
  return {
    state: few ? "unavailable" : "available",
    district_name: location.name,
    execution_mode: "fixture",
    reason: few ? "insufficient_complete_hotels" : null,
    discovered_count: count,
    usable_count: count,
    components,
    ranking: {
      weights: { night: 0.35, hot_hours: 0.25, persistence: 0.2, day: 0.2 },
      weight_label: "product defaults",
      complete_candidate_count: count,
      ranked_output: !few,
      hotels: Array.from({ length: count }, (_, index) => ({
        identity: { object_type: "node" as const, object_id: index + 1 },
        name: names[index],
        complete: true,
        relative_aggregate: few ? null : index / (count - 1),
        rank: few ? null : index + 1,
        components: Object.fromEntries(
          (["night", "hot_hours", "persistence", "day"] as const).map(
            (component) => {
              const values = componentValues[component];
              const value = values[index];
              const unique = [...new Set(values)].sort((a, b) => a - b);
              const percentile =
                unique.length === 1
                  ? 100
                  : 100 * (1 - unique.indexOf(value) / (unique.length - 1));
              return [
                component,
                {
                  component,
                  value,
                  unit:
                    component === "night" || component === "day"
                      ? "C"
                      : "hours",
                  threshold_celsius:
                    component === "hot_hours" || component === "persistence"
                      ? 35
                      : null,
                  provenance: "district fixture analysis",
                  tile_id:
                    few && index < 2
                      ? `${component}-tie`
                      : `${component}-${index}`,
                  tile_resolution_m: 80,
                  quality: "containing_tile",
                  distance_m: 0,
                  coverage: few ? 0.72 : 0.94,
                  caveats: [
                    "Candidate-relative evidence; not an absolute heat score.",
                  ],
                  percentile,
                },
              ];
            }
          )
        ) as HotelRankingHotel["components"],
      })),
    },
  };
};

export const scenarioLocations = locations;
export const hotelLocations: LocationSelection[] = [
  {
    id: "downtown-san-antonio",
    name: "Downtown San Antonio",
    context: "Supported hotel ranking district",
    latitude: 29.425,
    longitude: -98.486,
  },
];
export const scenarioIds = ["harbor", "civic", "garden"];
export function resolveLocation(id?: string) {
  return locations.find((location) => location.id === id) ?? locations[0];
}
export function resolveMode(options: RequestOptions): MockMode {
  return (
    options.mode ??
    (new URLSearchParams(window.location.search).get("state") as MockMode) ??
    "success"
  );
}
export function mockTripAnalyze(
  location: LocationSelection,
  date: string,
  options: RequestOptions = {}
): Promise<TripResponse> {
  return delayed(
    resolveMode(options),
    () => makeTrip(location, date, location.id === "garden"),
    options.signal
  );
}
export function mockHotelRanking(
  location: LocationSelection,
  options: RequestOptions = {}
): Promise<HotelRankResponse> {
  return delayed(
    resolveMode(options),
    () => makeHotels(location, resolveMode(options) === "degraded"),
    options.signal
  );
}
function delayed<T>(
  mode: MockMode,
  create: () => T,
  signal?: AbortSignal
): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      if (mode === "error")
        reject(new Error("The local demonstration data is unavailable."));
      else if (mode === "empty")
        reject(
          Object.assign(
            new Error("No fixture is available for this selection."),
            { code: "EMPTY" }
          )
        );
      else resolve(create());
    }, 1400);
    signal?.addEventListener(
      "abort",
      () => {
        window.clearTimeout(timer);
        reject(new DOMException("Request cancelled", "AbortError"));
      },
      { once: true }
    );
  });
}
