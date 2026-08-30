import { afterEach, describe, expect, it, vi } from "vitest";
import briscoe from "../../../fixtures/trips/briscoe-tower-unavailable.trip.json";
import cathedral from "../../../fixtures/trips/cathedral-governors-palace.trip.json";
import mainPlaza from "../../../fixtures/trips/main-plaza-market-square.trip.json";
import menger from "../../../fixtures/trips/menger-alamo.trip.json";
import { dataClient } from "../services/dataClient";
import type { TripAnalysisRequest } from "../types";

const requests: TripAnalysisRequest[] = [
  {
    mode: "curated",
    execution_mode: "fixture",
    origin_latitude: 29.4245914,
    origin_longitude: -98.4864288,
    destination_latitude: 29.425833,
    destination_longitude: -98.485833,
    landmark_name: "The Alamo",
    district_name: "Downtown San Antonio",
    date: "2024-07-15",
    start_hour: 8,
    end_hour: 20,
    cautious: false,
  },
  {
    mode: "exploratory",
    execution_mode: "fixture",
    origin_latitude: 29.4245773,
    origin_longitude: -98.4935063,
    destination_latitude: 29.4254009,
    destination_longitude: -98.4994785,
    landmark_name: "Historic Market Square (El Mercado)",
    district_name: "Downtown San Antonio",
    date: "2024-07-15",
    start_hour: 10,
    end_hour: 17,
    cautious: false,
  },
  {
    mode: "exploratory",
    execution_mode: "fixture",
    origin_latitude: 29.424559,
    origin_longitude: -98.4942042,
    destination_latitude: 29.4248225,
    destination_longitude: -98.4959872,
    landmark_name: "Spanish Governor's Palace",
    district_name: "Downtown San Antonio",
    date: "2024-07-15",
    start_hour: 10,
    end_hour: 17,
    cautious: false,
  },
  {
    mode: "exploratory",
    execution_mode: "fixture",
    origin_latitude: 29.4228983,
    origin_longitude: -98.4888465,
    destination_latitude: 29.4190825,
    destination_longitude: -98.4835734,
    landmark_name: "Tower of the Americas",
    district_name: "Downtown San Antonio",
    date: "2024-07-15",
    start_hour: 10,
    end_hour: 17,
    cautious: false,
  },
];

const snapshots = [menger, mainPlaza, cathedral, briscoe];

function apiEnvelope(
  snapshot: (typeof snapshots)[number],
  request: TripAnalysisRequest
) {
  return {
    ...snapshot,
    request_identity: `${request.mode}:${request.date}:${request.start_hour}-${request.end_hour}`,
    mode: request.mode,
    execution_mode: request.execution_mode,
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("trip-contract-v2 API decoder", () => {
  it.each(
    requests.map(
      (request, index) =>
        [request.landmark_name, request, snapshots[index]] as const
    )
  )(
    "decodes the committed %s fixture through the request boundary",
    async (_name, request, snapshot) => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          new Response(JSON.stringify(apiEnvelope(snapshot, request)), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          })
        )
      );

      const result = await dataClient.analyzeTripAnalysis(request);

      expect(result.schema_version).toBe("trip-contract-v2");
      expect(result.state).toBe(snapshot.state);
      expect(
        result.hotels?.component_temporal_metadata?.night.caveat_code
      ).toBe(snapshot.hotels?.component_temporal_metadata?.night.caveat_code);
      expect(result.hotels?.enrichment.code).toBe(
        snapshot.hotels?.enrichment.code
      );
      expect(result.routes?.route_set_state).toBe(
        snapshot.routes?.route_set_state
      );
      expect(result.unavailable?.code).toBe(snapshot.unavailable?.code);
    }
  );

  it("rejects an opaque hotel object and unknown v2 envelope fields", async () => {
    const request = requests[0];
    const malformed = {
      ...apiEnvelope(menger, request),
      hotels: { ranked: [] },
      unexpected: true,
    };
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify(malformed), { status: 200 })
        )
    );

    await expect(dataClient.analyzeTripAnalysis(request)).rejects.toThrow(
      "Invalid trip analysis response"
    );
  });
});
