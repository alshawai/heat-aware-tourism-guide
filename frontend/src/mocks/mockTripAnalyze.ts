import type { LocationSelection, RequestOptions } from "../types";
import { mockTripAnalyze as analyze } from "./data";

export function mockTripAnalyze(
  location: LocationSelection,
  date: string,
  options: RequestOptions = {}
) {
  return analyze(location, date, options);
}
