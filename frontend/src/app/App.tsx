import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppProvider } from "./AppState";
import { AppShell } from "./AppShell";
import {
  HotelDetailScreen,
  HotelLocationScreen,
  HotelRankingScreen,
} from "../features/hotels/HotelScreens";
import {
  RouteDetailScreen,
  TripResultsScreen,
  TripSetupScreen,
} from "../features/trip/TripScreens";
import { WelcomeScreen } from "../screens/WelcomeScreen";

export function App() {
  return (
    <BrowserRouter>
      <AppProvider>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<WelcomeScreen />} />
            <Route path="trip/setup" element={<TripSetupScreen />} />
            <Route path="trip/results" element={<TripResultsScreen />} />
            <Route
              path="trip/routes/:routeId"
              element={<RouteDetailScreen />}
            />
            <Route path="hotels/location" element={<HotelLocationScreen />} />
            <Route path="hotels/results" element={<HotelRankingScreen />} />
            <Route path="hotels/:hotelId" element={<HotelDetailScreen />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </AppProvider>
    </BrowserRouter>
  );
}
