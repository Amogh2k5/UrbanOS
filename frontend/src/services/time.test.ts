import { describe, expect, it } from "vitest";
import { formatSingaporeClock, formatSingaporeDate, formatSingaporeDateTime, formatSingaporeTime } from "./time";

describe("Singapore timestamp formatting", () => {
  const instant = "2026-10-20T00:00:00Z";

  it("renders time in UTC+08 regardless of browser timezone", () => {
    expect(formatSingaporeTime(instant)).toBe("08:00");
  });

  it("renders date and time in Singapore", () => {
    expect(formatSingaporeDateTime(instant)).toBe("20 Oct 2026, 08:00");
    expect(formatSingaporeDate(instant)).toBe("20 Oct 2026");
    expect(formatSingaporeClock(new Date(instant))).toBe("08:00:00 | 20 Oct 2026");
  });

  it("shows invalid timestamps as unavailable", () => {
    expect(formatSingaporeDateTime("not-a-date")).toBe("—");
  });
});
