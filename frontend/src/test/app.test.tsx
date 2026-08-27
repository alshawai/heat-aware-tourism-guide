import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ProvenanceFooter } from "../components/Shared";
import { mockHotelRanking } from "../mocks/mockHotelRanking";
import { mockTripAnalyze } from "../mocks/mockTripAnalyze";
import { scenarioLocations } from "../mocks/data";

describe("mock data boundary", () => {
  it("delays trip analysis and preserves metric identity", async () => {
    vi.useFakeTimers();
    const request = mockTripAnalyze(scenarioLocations[2], "2026-09-02");
    let settled = false;
    request.then(() => {
      settled = true;
    });
    await vi.advanceTimersByTimeAsync(1000);
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(400);
    await expect(request).resolves.toMatchObject({
      metric: { actualHeatIndex: false },
    });
    vi.useRealTimers();
  });

  it("returns a scenario with ties and fewer than five hotels", async () => {
    vi.useFakeTimers();
    const request = mockHotelRanking(scenarioLocations[1]);
    await vi.advanceTimersByTimeAsync(1400);
    const result = await request;
    expect(result.usableCount).toBeLessThan(5);
    expect(result.hotels.some((hotel) => hotel.tieLabel)).toBe(true);
    vi.useRealTimers();
  });
});

describe("result provenance", () => {
  it("renders screen-specific source, date, confidence, and coverage", () => {
    render(
      <ProvenanceFooter
        value={{
          source: "mock",
          dataDate: "2026-08-23",
          confidence: "Low",
          coverage: "42%",
        }}
      />
    );
    expect(screen.getByText("mock")).toBeInTheDocument();
    expect(screen.getByText("2026-08-23")).toBeInTheDocument();
    expect(screen.getByText("Low")).toBeInTheDocument();
    expect(screen.getByText("42%")).toBeInTheDocument();
  });
});
