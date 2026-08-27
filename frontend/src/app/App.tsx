import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppProvider } from "./AppState";
import { AppShell } from "./AppShell";
import {
  HotelDetailScreen,
  HotelLocationScreen,
  HotelRankingScreen,
} from "../features/hotels/HotelScreens";
import {
  BestTimeScreen,
  RouteComparisonScreen,
  SelectedRouteScreen,
  WalkDateScreen,
  WalkLocationScreen,
} from "../features/walk/WalkScreens";
import { WelcomeScreen } from "../screens/WelcomeScreen";

export function App() {
  return (
    <BrowserRouter>
      <AppProvider>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<WelcomeScreen />} />
            <Route path="walk/location" element={<WalkLocationScreen />} />
            <Route path="walk/date" element={<WalkDateScreen />} />
            <Route path="walk/result" element={<BestTimeScreen />} />
            <Route path="walk/routes" element={<RouteComparisonScreen />} />
            <Route
              path="walk/routes/:routeId"
              element={<SelectedRouteScreen />}
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
