/**
 * Parse interval_seconds from backend (integer seconds) to minutes for form display.
 * Serialize minutes back to seconds for API.
 */

export interface IntervalParts {
  minutes: number;
}

export function parseInterval(intervalSeconds: number | undefined | null): IntervalParts {
  if (!intervalSeconds || intervalSeconds <= 0) {
    return { minutes: 60 };
  }
  return { minutes: Math.round(intervalSeconds / 60) };
}

export function serializeInterval(minutes: number): number {
  return (minutes || 60) * 60;
}
