/**
 * Trip-setup time-window rules, mirrored from `TimeWindow` in
 * `app/domain/environment.py`.
 *
 * The server's window is half-open on whole hours: `hours = range(start, end)`.
 * Both bounds are validated in `0..23` and `start < end`, so the latest hour a
 * returned series can contain is 22, and the longest window is
 * `MAX_WINDOW_HOURS` hours. Travelers read windows inclusively, so every label
 * here renders the last covered hour rather than the exclusive end.
 */
export const MIN_HOUR = 0;
export const MAX_HOUR = 23;
export const MAX_WINDOW_HOURS = 12;

/** Selectable window bounds. `end_hour` is exclusive, so it may reach 23. */
export const START_HOUR_OPTIONS = Array.from(
  { length: MAX_HOUR - MIN_HOUR },
  (_, index) => MIN_HOUR + index
);
export const END_HOUR_OPTIONS = Array.from(
  { length: MAX_HOUR - MIN_HOUR },
  (_, index) => MIN_HOUR + index + 1
);

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

export function isValidDate(value: string): boolean {
  if (!ISO_DATE.test(value)) {
    return false;
  }
  const parsed = new Date(`${value}T00:00:00Z`);
  return (
    !Number.isNaN(parsed.getTime()) &&
    parsed.toISOString().slice(0, 10) === value
  );
}

/** The last hour a half-open window actually covers. */
export function lastHour(endHour: number): number {
  return endHour - 1;
}

export function formatHourLabel(hour: number): string {
  return `${String(hour).padStart(2, "0")}:00`;
}

/** Inclusive traveler-facing label, e.g. `(8, 20)` reads "08:00 to 19:00". */
export function formatWindowLabel(startHour: number, endHour: number): string {
  return `${formatHourLabel(startHour)} to ${formatHourLabel(lastHour(endHour))}`;
}

export function windowHours(startHour: number, endHour: number): number {
  return endHour - startHour;
}

/**
 * Whether an hour can be requested on its own as `(hour, hour + 1)`.
 *
 * Hour 23 is excluded because its exclusive end would be 24, which the server's
 * `TimeWindow` rejects. A returned series cannot reach hour 23 either, so this
 * stays a documented defensive guard rather than a case travelers can hit.
 */
export function isOverridableHour(hour: number): boolean {
  return Number.isInteger(hour) && hour >= MIN_HOUR && hour < MAX_HOUR;
}

/** The single-hour window sent when the traveler overrides the best time. */
export function singleHourWindow(hour: number): {
  startHour: number;
  endHour: number;
} {
  return { startHour: hour, endHour: hour + 1 };
}

/**
 * Validate the traveler's window against the server's invariants before
 * spending a billable analysis on a request the server would reject.
 */
export function validateTimeWindow(
  startHour: number,
  endHour: number
): string | null {
  if (startHour >= endHour) {
    return startHour === endHour
      ? "Start time must be earlier than end time."
      : "End time must be later than start time.";
  }
  if (windowHours(startHour, endHour) > MAX_WINDOW_HOURS) {
    return `The time window cannot exceed ${MAX_WINDOW_HOURS} hours.`;
  }
  return null;
}

export const INVALID_DATE_MESSAGE = "Enter a valid date.";
export const SAME_ENDPOINTS_MESSAGE = "Choose two different endpoints.";
