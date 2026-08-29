import type {
  HotelComponentName,
  HotelRankResponse,
  HotelRankingHotel,
} from "../../types";

export const HOTEL_COMPONENTS: HotelComponentName[] = [
  "night",
  "hot_hours",
  "persistence",
  "day",
];

export const HOTEL_COMPONENT_LABELS: Record<HotelComponentName, string> = {
  night: "Night heat",
  hot_hours: "Hot hours",
  persistence: "Persistence",
  day: "Day heat",
};

function identity(hotel: HotelRankingHotel) {
  return `${hotel.identity.object_type}-${hotel.identity.object_id}`;
}

export function rerankHotels(
  response: HotelRankResponse,
  weights: Record<HotelComponentName, number>,
  weightLabel: "product defaults" | "custom" = "custom"
): HotelRankResponse {
  if (!response.ranking) return response;
  const complete = response.ranking.hotels.filter(
    (hotel) =>
      hotel.complete &&
      HOTEL_COMPONENTS.every(
        (component) => hotel.components[component].percentile !== null
      )
  );
  const aggregates = new Map(
    complete.map((hotel) => {
      const groups = new Map<string, [HotelComponentName, number]>();
      HOTEL_COMPONENTS.forEach((component) => {
        const key = hotel.components[component].correlation_key ?? component;
        const current = groups.get(key);
        if (!current) {
          groups.set(key, [component, weights[component]]);
        } else {
          groups.set(key, [current[0], current[1] + weights[component]]);
        }
      });
      const activeWeight = [...groups.values()].reduce(
        (total, [, weight]) => total + weight,
        0
      );
      const aggregate = [...groups.values()].reduce(
        (total, [component, weight]) =>
          total +
          ((1 - (hotel.components[component].percentile ?? 0) / 100) * weight) /
            activeWeight,
        0
      );
      return [identity(hotel), Number(aggregate.toFixed(6))];
    })
  );
  const aggregateValues = [...new Set(aggregates.values())].sort(
    (a, b) => a - b
  );
  const rankedOutput = complete.length >= 5;
  if (!rankedOutput) {
    return {
      ...response,
      ranking: {
        ...response.ranking,
        weights,
        weight_label: weightLabel,
        complete_candidate_count: complete.length,
        ranked_output: false,
        hotels: response.ranking.hotels.map((hotel) => ({
          ...hotel,
          relative_aggregate: aggregates.get(identity(hotel)) ?? null,
          rank: null,
          relative_percentile: null,
        })),
      },
    };
  }
  const orderedComplete = [...complete].sort((left, right) => {
    const difference =
      (aggregates.get(identity(left)) ?? 0) -
      (aggregates.get(identity(right)) ?? 0);
    return difference || identity(left).localeCompare(identity(right));
  });
  const ranked = orderedComplete.map((hotel) => {
    const aggregate = aggregates.get(identity(hotel)) ?? 0;
    const valueIndex = aggregateValues.indexOf(aggregate);
    return {
      ...hotel,
      relative_aggregate: aggregate,
      rank:
        orderedComplete.findIndex(
          (candidate) => aggregates.get(identity(candidate)) === aggregate
        ) + 1,
      relative_percentile:
        aggregateValues.length === 1
          ? 100
          : 100 * (1 - valueIndex / (aggregateValues.length - 1)),
    };
  });
  const incomplete = response.ranking.hotels
    .filter((hotel) => !aggregates.has(identity(hotel)))
    .map((hotel) => ({
      ...hotel,
      relative_aggregate: null,
      rank: null,
      relative_percentile: null,
    }));
  return {
    ...response,
    ranking: {
      ...response.ranking,
      weights,
      weight_label: weightLabel,
      complete_candidate_count: complete.length,
      ranked_output: true,
      hotels: [...ranked, ...incomplete],
    },
  };
}
