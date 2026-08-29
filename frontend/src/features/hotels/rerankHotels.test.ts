import { describe, expect, it } from "vitest";
import type {
  HotelComponentName,
  HotelRankResponse,
  HotelRankingHotel,
} from "../../types";
import { HOTEL_COMPONENTS, rerankHotels } from "./rerankHotels";

function hotel(
  id: number,
  name: string,
  percentiles: Record<HotelComponentName, number | null>
): HotelRankingHotel {
  return {
    identity: { object_type: "node", object_id: id },
    name,
    complete: Object.values(percentiles).every((value) => value !== null),
    relative_aggregate: null,
    rank: null,
    components: Object.fromEntries(
      HOTEL_COMPONENTS.map((component) => [
        component,
        {
          component,
          value: percentiles[component],
          unit: component === "night" || component === "day" ? "C" : "hours",
          threshold_celsius:
            component === "hot_hours" || component === "persistence"
              ? 35
              : null,
          provenance: "fixture",
          tile_id: `${component}-${id}`,
          tile_resolution_m: 80,
          quality: "containing_tile",
          distance_m: 0,
          coverage: 1,
          confidence: "high",
          caveats: [],
          percentile: percentiles[component],
        },
      ])
    ) as unknown as HotelRankingHotel["components"],
  };
}

const response: HotelRankResponse = {
  state: "available",
  district_name: "Downtown",
  execution_mode: "fixture",
  reason: null,
  discovered_count: 6,
  usable_count: 6,
  components: {},
  ranking: {
    weights: { night: 0.35, hot_hours: 0.25, persistence: 0.2, day: 0.2 },
    weight_label: "product defaults",
    complete_candidate_count: 5,
    ranked_output: true,
    hotels: [
      hotel(1, "Night winner", {
        night: 100,
        hot_hours: 0,
        persistence: 0,
        day: 0,
      }),
      hotel(2, "Day winner", {
        night: 0,
        hot_hours: 0,
        persistence: 0,
        day: 100,
      }),
      hotel(3, "Tie one", {
        night: 50,
        hot_hours: 50,
        persistence: 50,
        day: 50,
      }),
      hotel(4, "Tie two", {
        night: 50,
        hot_hours: 50,
        persistence: 50,
        day: 50,
      }),
      hotel(5, "Middle", {
        night: 25,
        hot_hours: 25,
        persistence: 25,
        day: 25,
      }),
      hotel(6, "Incomplete", {
        night: null,
        hot_hours: 100,
        persistence: 100,
        day: 100,
      }),
    ],
  },
};

describe("local hotel reranking", () => {
  it("reranks the whole complete candidate set and preserves ties", () => {
    const ranked = rerankHotels(response, {
      night: 1,
      hot_hours: 0,
      persistence: 0,
      day: 0,
    });

    expect(ranked.ranking?.hotels.map((candidate) => candidate.name)).toEqual([
      "Night winner",
      "Tie one",
      "Tie two",
      "Middle",
      "Day winner",
      "Incomplete",
    ]);
    expect(ranked.ranking?.hotels.map((candidate) => candidate.rank)).toEqual([
      1,
      2,
      2,
      4,
      5,
      null,
    ]);
    expect(
      ranked.ranking?.hotels.map((candidate) => candidate.relative_percentile)
    ).toEqual([
      100,
      100 * (1 - 1 / 3),
      100 * (1 - 1 / 3),
      100 * (1 - 2 / 3),
      0,
      null,
    ]);
    expect(ranked.ranking?.hotels[0].relative_aggregate).toBe(0);
    expect(ranked.ranking?.hotels[4].relative_aggregate).toBe(1);
    expect(ranked.ranking?.weight_label).toBe("custom");
  });

  it("keeps fewer than five complete candidates explicitly unranked", () => {
    const unavailable = {
      ...response,
      state: "unavailable" as const,
      ranking: response.ranking
        ? { ...response.ranking, hotels: response.ranking.hotels.slice(0, 4) }
        : null,
    };

    const ranked = rerankHotels(unavailable, {
      night: 1,
      hot_hours: 0,
      persistence: 0,
      day: 0,
    });

    expect(ranked.ranking?.ranked_output).toBe(false);
    expect(
      ranked.ranking?.hotels.every((candidate) => candidate.rank === null)
    ).toBe(true);
    expect(
      ranked.ranking?.hotels.every(
        (candidate) => candidate.relative_percentile === null
      )
    ).toBe(true);
  });
});
