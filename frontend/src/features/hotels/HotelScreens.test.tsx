import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppProvider, useAppState } from "../../app/AppState";
import { mockHotelRanking } from "../../mocks/mockHotelRanking";
import { scenarioLocations } from "../../mocks/data";
import { HotelDetailScreen, HotelRankingScreen } from "./HotelScreens";

function HotelRankingHarness() {
  const { hotelLocation, setHotelLocation } = useAppState();
  useEffect(() => setHotelLocation(scenarioLocations[0]), []);
  return hotelLocation ? <HotelRankingScreen /> : null;
}

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/");
});

describe("hotel ranking screens", () => {
  it("loads the backend contract and displays district and assignment evidence", async () => {
    vi.useFakeTimers();
    const pending = mockHotelRanking(scenarioLocations[0]);
    await vi.advanceTimersByTimeAsync(1400);
    const response = await pending;
    vi.useRealTimers();
    const fetchMock = vi.fn().mockImplementation((url: string) =>
      Promise.resolve(
        jsonResponse(
          url === "/health"
            ? {
                status: "ok",
                deployment_profile: "local",
                mode: "fixture",
                execution_capability: "fixture-only",
              }
            : response
        )
      )
    );
    vi.stubGlobal("fetch", fetchMock);
    window.history.replaceState({}, "", "/hotels/results");
    const user = userEvent.setup();

    render(
      <BrowserRouter>
        <AppProvider>
          <Routes>
            <Route path="/hotels/results" element={<HotelRankingHarness />} />
            <Route path="/hotels/:hotelId" element={<HotelDetailScreen />} />
          </Routes>
        </AppProvider>
      </BrowserRouter>
    );

    expect(await screen.findByText("Component evidence")).toBeInTheDocument();
    expect(
      screen.getByText("Current weighting: product defaults")
    ).toBeInTheDocument();
    expect(screen.getAllByText("94%").length).toBeGreaterThan(0);
    expect(
      screen.getAllByText(
        "Candidate-relative evidence; not an absolute heat score."
      ).length
    ).toBeGreaterThan(0);
    expect(screen.getAllByText("°C").length).toBeGreaterThan(0);
    expect(screen.getAllByText("hours").length).toBeGreaterThan(0);
    // The shell probes /health once on mount and rankHotels probes it again to
    // pick its execution mode, so the ranking costs three requests in total.
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/hotels/rank",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          district_name: "Downtown San Antonio",
          execution_mode: "fixture",
        }),
      })
    );

    for (const [label, value] of [
      ["Night heat weight", "100"],
      ["Hot hours weight", "0"],
      ["Persistence weight", "0"],
      ["Day heat weight", "0"],
    ] as const) {
      const input = screen.getByLabelText(label);
      await user.clear(input);
      await user.type(input, value);
    }
    await user.click(
      screen.getByRole("button", { name: "Apply local weights" })
    );
    expect(screen.getByText("Current weighting: custom")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(3);

    await user.click(
      screen.getByRole("link", { name: "View details for Canopy House" })
    );

    await waitFor(() => {
      expect(screen.getAllByText("Assignment quality")).toHaveLength(4);
      expect(screen.getAllByText("Confidence")).toHaveLength(4);
    });
    expect(screen.getAllByText("containing tile")).toHaveLength(4);
    expect(screen.getAllByText("80 m")).toHaveLength(4);
    expect(
      screen.getByText(
        "Dimensionless percentile aggregate; no mixed-unit raw values are summed."
      )
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});
