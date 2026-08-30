import { afterEach, describe, expect, it, vi } from "vitest";
import { dataClient } from "./dataClient";
import type { LocationSelection } from "../types";

const location: LocationSelection = {
  id: "downtown-san-antonio",
  name: "Downtown San Antonio",
  context: "Supported hotel ranking district",
  latitude: 29.425,
  longitude: -98.486,
};

const health = {
  status: "ok",
  deployment_profile: "public-fixture",
  mode: "fixture",
  execution_capability: "fixture-only",
};

const ranking = {
  state: "available",
  district_name: "Downtown San Antonio",
  execution_mode: "fixture",
  reason: null,
  discovered_count: 6,
  usable_count: 6,
  components: {},
  ranking: {
    weights: { night: 0.35, hot_hours: 0.25, persistence: 0.2, day: 0.2 },
    weight_label: "product defaults",
    complete_candidate_count: 6,
    ranked_output: true,
    hotels: [],
  },
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("rankHotels cold-start resilience", () => {
  it("retries a waking (503) ranking response and resolves once the service is up", async () => {
    vi.useFakeTimers();
    const fetchMock = vi
      .fn()
      .mockImplementationOnce(() => Promise.resolve(json(health)))
      .mockImplementationOnce(() =>
        Promise.resolve(json({ detail: "waking" }, 503))
      )
      .mockImplementationOnce(() =>
        Promise.resolve(json({ detail: "waking" }, 503))
      )
      .mockImplementationOnce(() => Promise.resolve(json(ranking)));
    vi.stubGlobal("fetch", fetchMock);
    const onColdStartRetry = vi.fn();

    const pending = dataClient.rankHotels(location, { onColdStartRetry });
    await vi.advanceTimersByTimeAsync(5_000);
    const result = await pending;

    expect(result.state).toBe("available");
    expect(fetchMock).toHaveBeenCalledTimes(4); // 1 health probe + 3 ranking attempts
    expect(onColdStartRetry.mock.calls).toEqual([[1], [2]]);
  });

  it("surfaces an error only after the cold-start retry budget is exhausted", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn((input: string) =>
      Promise.resolve(
        input === "/health"
          ? json(health)
          : json({ detail: { error: "still waking" } }, 503)
      )
    );
    vi.stubGlobal("fetch", fetchMock);
    const onColdStartRetry = vi.fn();

    const pending = dataClient.rankHotels(location, { onColdStartRetry });
    const rejection = expect(pending).rejects.toThrow();
    await vi.advanceTimersByTimeAsync(60_000);
    await rejection;

    // Initial attempt plus five retries before the failure is surfaced.
    expect(onColdStartRetry.mock.calls).toEqual([[1], [2], [3], [4], [5]]);
  });

  it("retries a per-attempt timeout without a caller signal", async () => {
    vi.useFakeTimers();
    let rankAttempts = 0;
    const fetchMock = vi.fn((input: string, init?: RequestInit) => {
      if (input === "/health") return Promise.resolve(json(health));
      rankAttempts += 1;
      if (rankAttempts === 1) {
        // First ranking attempt never settles on its own; it must time out.
        return new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(
              init.signal?.reason ?? new DOMException("Aborted", "AbortError")
            )
          );
        });
      }
      return Promise.resolve(json(ranking));
    });
    vi.stubGlobal("fetch", fetchMock);
    const onColdStartRetry = vi.fn();

    const pending = dataClient.rankHotels(location, { onColdStartRetry });
    await vi.advanceTimersByTimeAsync(20_000);
    const result = await pending;

    expect(result.state).toBe("available");
    expect(onColdStartRetry.mock.calls).toEqual([[1]]);
    expect(rankAttempts).toBe(2);
  });

  it("propagates a caller abort immediately and does not retry", async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn(
      (_input: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(
              init.signal?.reason ?? new DOMException("Aborted", "AbortError")
            )
          );
        })
    );
    vi.stubGlobal("fetch", fetchMock);

    const pending = dataClient.rankHotels(location, {
      signal: controller.signal,
    });
    controller.abort();

    await expect(pending).rejects.toThrow();
    expect(fetchMock).toHaveBeenCalledTimes(1); // health probe only, never retried
  });
});
