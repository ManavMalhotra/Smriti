import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import Dashboard from "../pages/Dashboard";
import summary from "../fixtures/summary.json";

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

function documentResponse() {
  return jsonResponse({
    id: "d-01",
    patient_id: summary.patient.id,
    doc_type: "lab_report",
    doc_type_confidence: 0.9,
    capture_type: "printed",
    doc_date: "2025-11-02",
    collection_date: "2025-11-02",
    lab_name: null,
    page_count: 1,
    quality_score: 0.8,
    status: "done",
    processed_at: "2026-10-23T00:00:00Z",
    created_at: "2026-10-23T00:00:00Z",
    consent: null,
    egress: [],
    page_text: [{ page: 1, text: "HbA1c 8.9 %", engine: "fake" }],
    observations: [],
    medications: [],
    pages: [{ page: 1, url: "/api/documents/d-01/page/1" }],
  });
}

function authenticatedFetch() {
  return vi.fn((url) => {
    if (url === "/api/auth/me") return Promise.resolve(jsonResponse(summary.patient));
    if (url === `/api/patients/${summary.patient.id}/summary`) {
      return Promise.resolve(jsonResponse(summary));
    }
    if (url === "/api/documents/d-01") return Promise.resolve(documentResponse());
    return Promise.reject(new Error(`Unexpected request: ${url}`));
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("App navigation", () => {
  it("opens the intake form and returns to the summary", async () => {
    vi.stubGlobal("fetch", authenticatedFetch());
    const user = userEvent.setup();
    render(<App />);

    expect(
      await screen.findByRole("heading", { level: 1, name: "P-01" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Add document" }));
    expect(
      screen.getByRole("heading", { level: 1, name: "Add a document" }),
    ).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Back to summary" }));
    expect(screen.getByRole("heading", { level: 1, name: "P-01" })).toHaveFocus();
  });

  it("opens a document review and returns to the summary", async () => {
    vi.stubGlobal("fetch", authenticatedFetch());
    const user = userEvent.setup();
    render(<App />);

    expect(
      await screen.findByRole("heading", { level: 1, name: "P-01" }),
    ).toBeInTheDocument();
    await user.click(
      await screen.findByRole("button", { name: "Review Lab report d-01" }),
    );

    expect(
      await screen.findByRole("heading", { level: 1, name: "Document review" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "Page 1 of the Lab report" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Back to summary" }));
    expect(screen.getByRole("heading", { level: 1, name: "P-01" })).toBeInTheDocument();
  });

  it("shows sign in when there is no session and loads the summary after login", async () => {
    const fetchMock = vi.fn((url) => {
      if (url === "/api/auth/me") {
        return Promise.resolve(
          jsonResponse({ error: { code: "unauthorized", message: "Sign in." } }, 401),
        );
      }
      if (url === "/api/auth/login") return Promise.resolve(jsonResponse(summary.patient));
      if (url === `/api/patients/${summary.patient.id}/summary`) {
        return Promise.resolve(jsonResponse(summary));
      }
      return Promise.reject(new Error(`Unexpected request: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Username"), "patient-one");
    await user.type(screen.getByLabelText("Password"), "test-password-123");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(
      await screen.findByRole("heading", { level: 1, name: "P-01" }),
    ).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      `/api/patients/${summary.patient.id}/summary`,
      expect.objectContaining({ credentials: "same-origin" }),
    );
  });
});

describe("Dashboard shell", () => {
  it("renders the four zones in fixed order", () => {
    render(<Dashboard data={summary} />);

    const headings = screen
      .getAllByRole("heading", { level: 2 })
      .map((heading) => heading.textContent);

    expect(headings).toEqual([
      "Coverage",
      "Problems",
      "Current medications",
      "Results",
      "Pending",
      "Documents",
    ]);
  });

  it("states the coverage gap verbatim", () => {
    render(<Dashboard data={summary} />);

    const gap = screen.getByText("No data for 10 months").closest(".gap-banner");
    expect(gap).not.toBeNull();
    expect(within(gap).getByText("2 Nov 2025 – 12 Sept 2026")).toBeInTheDocument();
  });

  it("shows the printed flag without computing an abnormality", () => {
    render(<Dashboard data={summary} />);

    expect(screen.getByText("H")).toBeInTheDocument();
    expect(screen.queryByText(/abnormal/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/\bhigh\b/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/\blow\b/i)).not.toBeInTheDocument();
  });

  it("opens and closes the source path for a result", async () => {
    const user = userEvent.setup();
    render(<Dashboard data={summary} />);

    await user.click(
      screen.getByRole("button", { name: /open source for hba1c/i }),
    );

    const source = screen.getByRole("region", { name: "Source" });
    expect(within(source).getByText(/d-01/)).toBeInTheDocument();
    expect(within(source).getByText(/page 1/i)).toBeInTheDocument();
    expect(within(source).getByText("0.61, 0.42, 0.78, 0.47")).toBeInTheDocument();

    await user.click(within(source).getByRole("button", { name: /close source/i }));
    expect(screen.queryByRole("region", { name: "Source" })).not.toBeInTheDocument();
  });

  it("renders pending actions and source documents", () => {
    render(<Dashboard data={summary} />);

    expect(screen.getByText("R/V after 2 weeks")).toBeInTheDocument();
    expect(screen.getByText(/Review/)).toBeInTheDocument();
    expect(screen.getByText("Lab report")).toBeInTheDocument();
    expect(screen.getByText("Processed")).toBeInTheDocument();
  });
});
