/**
 * Copilot UI tests: loading, grounded answers, errors and failure states.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import OverviewPage from "./page";
import { fetchChat } from "@/services/api";

vi.mock("@/services/api", async () => {
  const actual = await vi.importActual<typeof import("@/services/api")>(
    "@/services/api"
  );
  return { ...actual, fetchChat: vi.fn() };
});

const mockedFetchChat = vi.mocked(fetchChat);

const OVERVIEW_OK = {
  generated_at: "2026-10-12T05:05:19.810241+08:00",
  modules: [
    {
      id: "land",
      name: "Land",
      status: "normal",
      kpi: { label: "Land-Use Area", value: 796.8, unit: "km²" },
      updated_at: null,
      detail_route: "/planning/land",
    },
  ],
  alerts: [],
  ai_brief: "City status DISRUPTED (risk HIGH, confidence high).",
  domain_status: {},
};

const CITY_REPORT_OK = {
  generated_at: "2026-10-12T02:33:10.233228",
  overall_city_status: "DISRUPTED",
  overall_risk_level: "HIGH",
  domain_status: {},
  priority_incidents: [],
  cross_domain_impacts: [],
  city_level_recommendations: [],
  affected_zones: [],
  evidence: [],
  confidence: "high",
  limitations: [],
  source_reports: {},
  is_ml_prediction: false,
};

function mockEndpoints() {
  const spy = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const body = url.includes("/api/city/report") ? CITY_REPORT_OK : OVERVIEW_OK;
    return {
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => body,
    } as unknown as Response;
  });
  globalThis.fetch = spy as unknown as typeof fetch;
}

async function openCopilot() {
  render(<OverviewPage />);
  await waitFor(() =>
    expect(screen.getByTestId("city-situation")).toBeTruthy()
  );
  fireEvent.click(screen.getByTestId("copilot-toggle"));
  await waitFor(() => expect(screen.getByTestId("copilot-panel")).toBeTruthy());
}

describe("Copilot UI", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockEndpoints();
  });

  it("shows an intro that states the grounding and scope limits", async () => {
    await openCopilot();
    const intro = screen.getByTestId("copilot-intro");
    expect(intro.textContent).toContain("deterministic City Coordinator");
    expect(intro.textContent).toContain("say so rather than guess");
    expect(intro.textContent).toContain("not supported");
  });

  it("renders a grounded answer returned by the backend", async () => {
    mockedFetchChat.mockResolvedValue({
      response:
        "The current city status is DISRUPTED with HIGH risk. Fire could not " +
        "be assessed, so its condition is unknown.",
    });
    await openCopilot();

    fireEvent.change(screen.getByTestId("copilot-input"), {
      target: { value: "What is the city status?" },
    });
    fireEvent.click(screen.getByTestId("copilot-send"));

    await waitFor(() =>
      expect(screen.getByText(/current city status is DISRUPTED/)).toBeTruthy()
    );
  });

  it("forwards bounded conversation history with the question", async () => {
    mockedFetchChat.mockResolvedValue({ response: "First answer here." });
    await openCopilot();

    const input = screen.getByTestId("copilot-input");
    fireEvent.change(input, { target: { value: "first question" } });
    fireEvent.click(screen.getByTestId("copilot-send"));
    await waitFor(() => expect(screen.getByText("First answer here.")).toBeTruthy());

    mockedFetchChat.mockResolvedValue({ response: "Second answer here." });
    fireEvent.change(input, { target: { value: "second question" } });
    fireEvent.click(screen.getByTestId("copilot-send"));

    await waitFor(() => expect(screen.getByText("Second answer here.")).toBeTruthy());
    const lastCall = mockedFetchChat.mock.calls.at(-1);
    expect(lastCall?.[0]).toBe("second question");
    expect(Array.isArray(lastCall?.[2])).toBe(true);
    expect((lastCall?.[2] ?? []).length).toBeGreaterThan(0);
    // History is bounded.
    expect((lastCall?.[2] ?? []).length).toBeLessThanOrEqual(6);
  });

  it("surfaces a grounded fallback when the backend says it has no evidence", async () => {
    mockedFetchChat.mockResolvedValue({
      response:
        "I cannot answer that right now: the City Coordinator report is " +
        "unavailable, so there is no verified intelligence to ground an answer in.",
    });
    await openCopilot();

    fireEvent.change(screen.getByTestId("copilot-input"), {
      target: { value: "tomorrow's BKT price?" },
    });
    fireEvent.click(screen.getByTestId("copilot-send"));

    await waitFor(() =>
      expect(screen.getByText(/Coordinator report is unavailable/)).toBeTruthy()
    );
  });

  it("shows an error state without breaking the page", async () => {
    mockedFetchChat.mockRejectedValue(new Error("Chat request timed out"));
    await openCopilot();

    fireEvent.change(screen.getByTestId("copilot-input"), {
      target: { value: "status?" },
    });
    fireEvent.click(screen.getByTestId("copilot-send"));

    await waitFor(() =>
      expect(screen.getByTestId("copilot-error").textContent).toContain(
        "timed out"
      )
    );
    // The rest of the dashboard is unaffected.
    expect(screen.getAllByTestId("domain-kpi-card")).toHaveLength(1);
    expect(screen.getByTestId("city-situation-narrative")).toBeTruthy();
  });

  it("explains that the deterministic figures are unaffected on failure", async () => {
    mockedFetchChat.mockRejectedValue(new Error("network down"));
    await openCopilot();

    fireEvent.change(screen.getByTestId("copilot-input"), {
      target: { value: "status?" },
    });
    fireEvent.click(screen.getByTestId("copilot-send"));

    await waitFor(() =>
      expect(
        screen.getByText(/deterministic city status and KPI values/i)
      ).toBeTruthy()
    );
  });

  it("does not send an empty message", async () => {
    await openCopilot();
    fireEvent.change(screen.getByTestId("copilot-input"), {
      target: { value: "   " },
    });
    fireEvent.click(screen.getByTestId("copilot-send"));
    expect(mockedFetchChat).not.toHaveBeenCalled();
  });

  it("shows a loading indicator while the answer is pending", async () => {
    let resolveFn: (v: { response: string }) => void = () => {};
    mockedFetchChat.mockImplementation(
      () => new Promise<{ response: string }>((r) => (resolveFn = r))
    );
    await openCopilot();

    fireEvent.change(screen.getByTestId("copilot-input"), {
      target: { value: "status?" },
    });
    fireEvent.click(screen.getByTestId("copilot-send"));

    await waitFor(() =>
      expect(screen.getByTestId("copilot-loading")).toBeTruthy()
    );
    resolveFn({ response: "done" });
    await waitFor(() => expect(screen.getByText("done")).toBeTruthy());
    expect(screen.queryByTestId("copilot-loading")).toBeNull();
  });
});