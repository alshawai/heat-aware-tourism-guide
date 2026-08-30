import type { RouteComparisonResult, RouteDecisionState } from "../../types";

/** Traveler-facing heading for each backend route-decision state. */
export function routeDecisionHeading(result: RouteComparisonResult) {
  switch (result.decision_state) {
    case "shade_shadiest_recommended":
      return "Shadiest route recommended";
    case "shade_only_route_recommended":
      return "Only route recommended";
    case "nighttime_coolest_recommended":
      return "Coolest nighttime route recommended";
    case "mild_shortest_recommended":
      return "Shortest route recommended";
    case "insufficient_shade_comparison_required":
      return "Compare route trade-offs";
    case "shade_required":
      return "Shade analysis required";
    case "heat_unavailable":
      return "Route heat unavailable";
    default:
      return "Walking routes";
  }
}

/**
 * Short scan badge per decision state. Kept separate from the heading so a
 * route card can stay one line while the comparison header carries the full
 * wording.
 */
const DECISION_BADGES: Record<RouteDecisionState, string> = {
  shade_shadiest_recommended: "Shadiest",
  shade_only_route_recommended: "Only route",
  nighttime_coolest_recommended: "Coolest at night",
  mild_shortest_recommended: "Shortest",
  insufficient_shade_comparison_required: "Compare trade-offs",
  shade_required: "Shade pending",
  heat_unavailable: "Heat unavailable",
  no_suitable_returned_route: "No usable route",
};

export function decisionBadge(state: RouteDecisionState | null): string | null {
  return state ? DECISION_BADGES[state] : null;
}

/**
 * Turn the server's `unavailable.action` token into a traveler instruction.
 *
 * The tokens come from `UnavailableResult` in `app/api.py`; anything unmapped
 * falls back to generic recovery wording rather than printing the raw token.
 */
export function actionGuidance(action: string): string {
  switch (action) {
    case "choose_us_endpoints":
      return "Choose origin and destination within the United States.";
    case "edit_setup_or_use_live_data":
      return "Edit the setup, or ask a maintainer to enable live data.";
    default:
      return "Retry the analysis or edit the trip setup.";
  }
}
