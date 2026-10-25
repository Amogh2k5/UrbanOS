import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import FirePage from "./page";

vi.mock("@/services/api", () => ({
  fetchFireReport: vi.fn(),
}));

import { fetchFireReport } from "@/services/api";

describe("Fire page data scope", () => {
  beforeEach(() => vi.clearAllMocks());

  it("labels missing active counts unavailable and explains the published-feed limitation", async () => {
    vi.mocked(fetchFireReport).mockResolvedValue({
      generated_at: "2026-10-26T10:00:00+08:00",
      domain: "safety",
      subdomain: "fire",
      active_incidents: [],
      recent_incidents: [],
      active_incident_count: null,
      critical_incident_count: null,
      incidents_today: null,
      resolved_recent_count: null,
      regional_counts: { Central: null },
      historical_fire_counts: [{ year: 2024, fires: 1200, source: "official annual statistics" }],
      source_status: "historical_only",
      data_sources: [],
      limitations: [],
      warnings: [],
      errors: [],
      is_ml_prediction: false,
    });

    render(<FirePage />);
    expect(await screen.findByText("SCDF published incident reports may be incomplete or delayed; they are not a real-time dispatch feed. Annual fire statistics are historical.")).toBeTruthy();
    expect(screen.getAllByText("Unavailable").length).toBeGreaterThanOrEqual(4);
    expect(screen.getByText("Central: Unavailable")).toBeTruthy();
  });
});
