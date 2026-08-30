import type { LocationSelection } from "../../types";

const EXPLORATORY_SCENARIOS = [
  ["main-plaza", "historic-market-square-el-mercado"],
  ["san-fernando-cathedral", "spanish-governors-palace"],
  ["briscoe-western-art-museum", "tower-of-the-americas"],
] as const;

export function fixtureScenarioFor(
  origin: LocationSelection,
  destination: LocationSelection
) {
  const scenario = EXPLORATORY_SCENARIOS.find(
    ([originId, destinationId]) =>
      originId === origin.id && destinationId === destination.id
  );
  return scenario
    ? { date: "2024-07-15", startHour: 10, endHour: 17 }
    : undefined;
}
