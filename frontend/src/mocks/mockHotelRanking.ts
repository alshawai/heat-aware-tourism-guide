import type { LocationSelection, RequestOptions } from "../types";
import { mockHotelRanking as rank } from "./data";

export function mockHotelRanking(
  location: LocationSelection,
  options: RequestOptions = {}
) {
  return rank(location, options);
}
