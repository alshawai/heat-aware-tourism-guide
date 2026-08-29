import type {
  HotelResponse,
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
): HotelResponse => {
  const names = [
    "Canopy House",
    "Civic Lantern",
    "Riverstone Rooms",
    "Juniper Court",
    "The Meridian",
    "Market House",
  ];
  const values = few ? [31, 31, 44] : [24, 29, 35, 41, 48, 53];
  return {
    location,
    usableCount: values.length,
    weights: {
      "Night heat": 35,
      "Hot hours": 25,
      Persistence: 20,
      "Day heat": 20,
    },
    provenance: {
      source: "mock",
      dataDate: "2026-08-23",
      confidence: few ? "Moderate" : "High",
      coverage: few
        ? "3 usable hotels; below the preferred 5"
        : "6 usable hotels",
      note: "Weights are configurable product preferences, not scientific truth.",
    },
    hotels: values.map((value, index) => ({
      id: `hotel-${index + 1}`,
      name: names[index],
      percentile: Math.round(100 - value * 1.2),
      tieLabel: few && index < 2 ? "Tied at this position" : undefined,
      latitude: location.latitude + index * 0.001,
      longitude: location.longitude + index * 0.001,
      components: [
        { label: "Night heat", value, contribution: value * 0.35 },
        {
          label: "Hot hours",
          value: value + 3,
          contribution: (value + 3) * 0.25,
        },
        {
          label: "Persistence",
          value: value - 2,
          contribution: (value - 2) * 0.2,
        },
        {
          label: "Day heat",
          value: value + 5,
          contribution: (value + 5) * 0.2,
        },
      ],
    })),
  };
};

export const scenarioLocations = locations;
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
): Promise<HotelResponse> {
  return delayed(
    resolveMode(options),
    () => makeHotels(location, location.id === "civic"),
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
