import { scenarioLocations } from "../mocks/data";
import { mockHotelRanking } from "../mocks/mockHotelRanking";
import { mockTripAnalyze } from "../mocks/mockTripAnalyze";

export const dataClient = {
  analyzeTrip: mockTripAnalyze,
  rankHotels: mockHotelRanking,
  searchLocations(query: string) {
    const normalized = query.trim().toLowerCase();
    return scenarioLocations.filter(
      (location) =>
        !normalized ||
        `${location.name} ${location.context}`
          .toLowerCase()
          .includes(normalized)
    );
  },
};
