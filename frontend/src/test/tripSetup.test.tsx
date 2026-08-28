import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "../app/App";

const successResponse = {
  request_identity: "curated:2026-08-23:8",
  mode: "curated",
  execution_mode: "fixture",
  state: "success",
  best_time: { hourly: [] },
  hotels: { ranked: [] },
  routes: { alternatives: [] },
  unavailable: null,
  degraded_reasons: null,
};

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function mockFetch(...responses: Array<Response | Promise<Response>>) {
  const fetchMock = vi.fn();
  responses.forEach((response) => fetchMock.mockResolvedValueOnce(response));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/");
});

describe("curated Trip Setup", () => {
  it("loads fixture mode and submits the complete setup exactly once", async () => {
    const fetchMock = mockFetch(
      jsonResponse({ status: "ok", mode: "fixture" }),
      jsonResponse(successResponse)
    );
    const user = userEvent.setup();

    render(<App />);

    expect(await screen.findByText("Fixture replay")).toBeInTheDocument();
    expect(screen.getByText("Menger Hotel")).toBeInTheDocument();
    expect(screen.getByText("The Alamo")).toBeInTheDocument();
    expect(
      screen.getByText("Downtown San Antonio / Alamo Plaza")
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Date")).toHaveValue("2026-08-23");
    expect(screen.getByLabelText("Hour")).toHaveValue("8");
    expect(screen.getByLabelText(/Cautious guidance/)).not.toBeChecked();
    expect(screen.getByText(/United States/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Analyze trip" }));

    expect(await screen.findByText("Trip analysis ready")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock).toHaveBeenNthCalledWith(1, "/health", expect.any(Object));
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/trip/analyze",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode: "curated",
          origin_latitude: 29.421,
          origin_longitude: -98.491,
          destination_latitude: 29.425,
          destination_longitude: -98.484,
          landmark_name: "The Alamo",
          district_name: "Downtown San Antonio",
          date: "2026-08-23",
          hour: 8,
          cautious: false,
          execution_mode: "fixture",
        }),
      })
    );
  });

  it("preserves edits and retries when application mode is unavailable", async () => {
    const fetchMock = mockFetch(
      Promise.reject(new Error("offline")),
      jsonResponse({ status: "ok", mode: "live" })
    );
    const user = userEvent.setup();

    render(<App />);

    expect(
      await screen.findByText("Application mode unavailable")
    ).toBeInTheDocument();
    const date = screen.getByLabelText("Date");
    await user.clear(date);
    await user.type(date, "2026-09-01");
    expect(screen.getByRole("button", { name: "Analyze trip" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Check again" }));

    expect(await screen.findByText("Live data")).toBeInTheDocument();
    expect(date).toHaveValue("2026-09-01");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("validates fields without submitting or auto-submitting edits", async () => {
    const fetchMock = mockFetch(
      jsonResponse({ status: "ok", mode: "fixture" })
    );
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText("Fixture replay");
    const date = screen.getByLabelText("Date");
    await user.clear(date);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Analyze trip" }));

    expect(screen.getByText("Enter a valid date.")).toBeInTheDocument();
    expect(date).toHaveAttribute("aria-invalid", "true");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("announces busy state and disables setup controls", async () => {
    let resolveAnalysis!: (response: Response) => void;
    const pending = new Promise<Response>((resolve) => {
      resolveAnalysis = resolve;
    });
    mockFetch(jsonResponse({ status: "ok", mode: "fixture" }), pending);
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText("Fixture replay");
    await user.click(screen.getByRole("button", { name: "Analyze trip" }));

    expect(screen.getByRole("status")).toHaveTextContent("Analyzing trip...");
    expect(screen.getByLabelText("Date")).toBeDisabled();
    expect(screen.getByLabelText("Hour")).toBeDisabled();
    expect(screen.getByLabelText(/Cautious guidance/)).toBeDisabled();
    resolveAnalysis(jsonResponse(successResponse));
    expect(await screen.findByText("Trip analysis ready")).toBeInTheDocument();
  });

  it("retains degraded detail and clears it when setup changes", async () => {
    mockFetch(
      jsonResponse({ status: "ok", mode: "fixture" }),
      jsonResponse({
        ...successResponse,
        state: "degraded",
        hotels: null,
        degraded_reasons: {
          hotels: "Hotel ranking is temporarily unavailable.",
        },
      })
    );
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText("Fixture replay");
    await user.click(screen.getByRole("button", { name: "Analyze trip" }));

    const outcome = await screen.findByRole("status", {
      name: "Trip analysis outcome",
    });
    expect(
      within(outcome).getByText("Trip analysis ready with limitations")
    ).toBeInTheDocument();
    expect(
      within(outcome).getByText("Hotel ranking is temporarily unavailable.")
    ).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Hour"), "9");
    expect(screen.queryByText(/Trip analysis ready/)).not.toBeInTheDocument();
  });

  it("shows domain unavailability and returns to editing", async () => {
    mockFetch(
      jsonResponse({ status: "ok", mode: "fixture" }),
      jsonResponse({
        ...successResponse,
        state: "unavailable",
        best_time: null,
        hotels: null,
        routes: null,
        unavailable: {
          reason: "No fixture matches that date and hour.",
          recoverable: true,
        },
      })
    );
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText("Fixture replay");
    await user.click(screen.getByRole("button", { name: "Analyze trip" }));

    expect(
      await screen.findByText("No fixture matches that date and hour.")
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Edit setup" }));
    expect(
      screen.queryByText("No fixture matches that date and hour.")
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("Date")).toHaveFocus();
  });

  it("keeps analyzed setup values aligned across route remounts", async () => {
    mockFetch(
      jsonResponse({ status: "ok", mode: "fixture" }),
      jsonResponse({
        ...successResponse,
        request_identity: "curated:2026-08-23:9",
      }),
      jsonResponse({ status: "ok", mode: "fixture" })
    );
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText("Fixture replay");
    await user.selectOptions(screen.getByLabelText("Hour"), "9");
    await user.click(screen.getByRole("button", { name: "Analyze trip" }));
    await screen.findByText("Trip analysis ready");

    window.history.pushState({}, "", "/walk/date");
    window.dispatchEvent(new PopStateEvent("popstate"));
    await screen.findByText("Choose a place");
    await user.click(
      screen.getByRole("link", { name: "Heat-Aware Tourism Guide home" })
    );

    expect(await screen.findByText("Trip analysis ready")).toBeInTheDocument();
    expect(screen.getByLabelText("Hour")).toHaveValue("9");
  });

  it("clears a retained result when application mode changes", async () => {
    mockFetch(
      jsonResponse({ status: "ok", mode: "fixture" }),
      jsonResponse(successResponse),
      jsonResponse({ status: "ok", mode: "live" })
    );
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText("Fixture replay");
    await user.click(screen.getByRole("button", { name: "Analyze trip" }));
    await screen.findByText("Trip analysis ready");

    window.history.pushState({}, "", "/walk/date");
    window.dispatchEvent(new PopStateEvent("popstate"));
    await screen.findByText("Choose a place");
    await user.click(
      screen.getByRole("link", { name: "Heat-Aware Tourism Guide home" })
    );

    expect(await screen.findByText("Live data")).toBeInTheDocument();
    expect(screen.queryByText("Trip analysis ready")).not.toBeInTheDocument();
  });

  it.each([
    [
      "malformed response",
      jsonResponse({ ...successResponse, execution_mode: "live" }),
    ],
    [
      "mismatched request identity",
      jsonResponse({
        ...successResponse,
        request_identity: "curated:2026-08-23:9",
      }),
    ],
    [
      "inconsistent degraded response",
      jsonResponse({
        ...successResponse,
        state: "degraded",
        hotels: null,
        degraded_reasons: { routes: "Route confidence is limited." },
      }),
    ],
    ["request failure", jsonResponse({ detail: "failed" }, 503)],
    [
      "domain error",
      jsonResponse({
        ...successResponse,
        state: "error",
        best_time: null,
        hotels: null,
        routes: null,
        unavailable: { reason: "Provider timeout", recoverable: true },
      }),
    ],
  ])("offers a retry after %s", async (_name, failedResponse) => {
    const fetchMock = mockFetch(
      jsonResponse({ status: "ok", mode: "fixture" }),
      failedResponse,
      jsonResponse(successResponse)
    );
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText("Fixture replay");
    await user.click(screen.getByRole("button", { name: "Analyze trip" }));

    expect(
      await screen.findByText("We could not analyze this trip.")
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByText("Trip analysis ready")).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
  });
});
