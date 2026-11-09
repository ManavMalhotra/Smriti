import { act, render, screen, within } from "@testing-library/react";
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

function timelineResponse() {
  return jsonResponse({
    patient_id: summary.patient.id,
    reports: [
      {
        id: "r-01",
        document_id: "d-01",
        category: "lab",
        report_type: "lab_report",
        report_date: "2025-11-02",
        facility_name: "City Lab",
        title: "City Lab",
        summary: "HbA1c 8.9 %",
        page_start: 1,
        page_end: 1,
        status: "auto",
        reason: null,
        review_count: 0,
        facts: [],
      },
    ],
  });
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
    if (url === `/api/patients/${summary.patient.id}/timeline`) {
      return Promise.resolve(timelineResponse());
    }
    if (url === "/api/documents/d-01?page=1&offset=0") return Promise.resolve(documentResponse());
    return Promise.reject(new Error(`Unexpected request: ${url}`));
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState(null, "", "/");
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

  it("loads Queue from its URL after refresh and returns there from a document", async () => {
    window.history.replaceState(null, "", "#/queue");
    const baseFetch = authenticatedFetch();
    vi.stubGlobal("fetch", vi.fn((url, options) => url.startsWith("/api/jobs?")
      ? Promise.resolve(jsonResponse({ jobs: [{ id: "j-1", document_id: "d-01", state: "queued", total: 1 }], has_more: false }))
      : baseFetch(url, options)));
    const user = userEvent.setup();
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Queue" })).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Open document" }));
    expect(window.location.hash).toBe("#/documents/d-01");
    await screen.findByRole("heading", { name: "Document review" });
    await user.click(screen.getByRole("button", { name: "Back to queue" }));
    expect(window.location.hash).toBe("#/queue");
    expect(screen.getByRole("heading", { name: "Queue" })).toHaveFocus();
  });

  it("keeps document page controls and browser hash navigation in sync", async () => {
    window.history.replaceState(null, "", "#/documents/d-01?page=21");
    const baseFetch = authenticatedFetch();
    vi.stubGlobal("fetch", vi.fn(async (url, options) => {
      if (url.startsWith("/api/documents/d-01?")) {
        const page = Number(new URL(url, "http://localhost").searchParams.get("page"));
        return jsonResponse({ ...await documentResponse().json(), page_count: 73, detail_page: page,
          pages: [{ page, url: `/api/documents/d-01/page/${page}` }] });
      }
      return baseFetch(url, options);
    }));
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("img", { name: "Page 21 of the Lab report" });
    await user.click(screen.getByRole("button", { name: "Next page" }));
    await screen.findByRole("img", { name: "Page 22 of the Lab report" });
    expect(window.location.hash).toBe("#/documents/d-01?page=22");
    act(() => {
      window.history.replaceState(null, "", "#/documents/d-01?page=21");
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    await screen.findByRole("img", { name: "Page 21 of the Lab report" });
  });

  it("handles browser hash navigation and guards files not yet uploaded", async () => {
    vi.stubGlobal("fetch", authenticatedFetch());
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", { name: "P-01" });
    await user.click(screen.getByRole("button", { name: "Add document" }));
    expect(window.location.hash).toBe("#/intake");
    await user.upload(screen.getByLabelText("Document file"), new File(["one"], "one.png", { type: "image/png" }));
    act(() => {
      window.history.replaceState(null, "", "#/summary");
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(confirm).toHaveBeenCalledOnce();
    expect(window.location.hash).toBe("#/intake");
    expect(screen.getByRole("heading", { name: "Add a document" })).toBeInTheDocument();
    confirm.mockReturnValue(true);
    act(() => {
      window.history.replaceState(null, "", "#/summary");
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(screen.getByRole("heading", { name: "P-01" })).toBeInTheDocument();
    confirm.mockRestore();
  });

  it("opens a document review and returns to the summary", async () => {
    vi.stubGlobal("fetch", authenticatedFetch());
    const user = userEvent.setup();
    render(<App />);

    expect(
      await screen.findByRole("heading", { level: 1, name: "P-01" }),
    ).toBeInTheDocument();
    await user.click(
      await screen.findByRole("button", { name: /^Open City Lab from/ }),
    );

    expect(
      await screen.findByRole("heading", { level: 1, name: "Document review" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("img", { name: "Page 1 of the Lab report" }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Back to summary" }));
    expect(screen.getByRole("heading", { level: 1, name: "P-01" })).toBeInTheDocument();
  });

  it("uploads a batch and opens the selected document for review", async () => {
    const baseFetch = authenticatedFetch();
    let uploads = 0;
    const fetchMock = vi.fn((url, options) => {
      if (url === "/api/documents") {
        uploads += 1;
        return Promise.resolve(jsonResponse({ document_id: null, job_id: `j-${uploads}`, pages: null, status: "pending_intake" }, 202));
      }
      if (url.startsWith("/api/jobs/")) return Promise.resolve(jsonResponse({ state: "done", stage: "done", document_id: url.endsWith("j-1") ? "d-01" : "d-02", total_pages: 1, events: [], verification_state: "skipped" }));
      return baseFetch(url, options);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: "P-01" });
    await user.click(screen.getByRole("button", { name: "Add document" }));
    await user.upload(screen.getByLabelText("Document file"), [new File(["one"], "one.png", { type: "image/png" }), new File(["two"], "two.png", { type: "image/png" })]);
    await user.click(screen.getByLabelText(/permission to store/i));
    await user.click(screen.getByRole("button", { name: "Upload 2 documents" }));
    const first = within(screen.getByRole("region", { name: "one.png" }));
    await user.click(await first.findByRole("button", { name: "Review extracted fields" }));
    expect(await screen.findByRole("heading", { name: "Document review" })).toHaveFocus();
    expect((await screen.findByRole("img", { name: "Page 1 of the Lab report" })).querySelector("img")).toHaveAttribute("src", "/api/documents/d-01/page/1");
    expect(uploads).toBe(2);
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
      if (url === `/api/patients/${summary.patient.id}/timeline`) {
        return Promise.resolve(timelineResponse());
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

  it("does not show empty dashboard panels while the first summary loads", async () => {
    let resolveSummary;
    const summaryPromise = new Promise((resolve) => {
      resolveSummary = resolve;
    });
    const fetchMock = vi.fn((url) => {
      if (url === "/api/auth/me") {
        return Promise.resolve(
          jsonResponse({ error: { code: "unauthorized", message: "Sign in." } }, 401),
        );
      }
      if (url === "/api/auth/login") return Promise.resolve(jsonResponse(summary.patient));
      if (url === `/api/patients/${summary.patient.id}/summary`) return summaryPromise;
      if (url === `/api/patients/${summary.patient.id}/timeline`) {
        return Promise.resolve(timelineResponse());
      }
      return Promise.reject(new Error(`Unexpected request: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<App />);

    await screen.findByRole("heading", { name: "Sign in" });
    await user.type(screen.getByLabelText("Username"), "patient-one");
    await user.type(screen.getByLabelText("Password"), "test-password-123");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(
      await screen.findByRole("heading", { level: 1, name: "P-01" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("No results recorded.")).not.toBeInTheDocument();
    expect(screen.queryByText("No source documents.")).not.toBeInTheDocument();

    resolveSummary(jsonResponse(summary));
    expect(await screen.findByRole("heading", { name: "HbA1c" })).toBeInTheDocument();
  });
});

describe("Dashboard shell", () => {
  it("puts the history spine before the supporting zones", () => {
    render(<Dashboard data={summary} />);

    const headings = screen
      .getAllByRole("heading", { level: 2 })
      .map((heading) => heading.textContent);

    expect(headings).toEqual([
      "Coverage",
      "History",
      "Current medications",
      "Results",
      "Pending",
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

    const source = screen.getByRole("dialog", { name: "Source" });
    expect(within(source).getByText(/d-01/)).toBeInTheDocument();
    expect(within(source).getByText(/page 1/i)).toBeInTheDocument();
    expect(
      within(source).getByText(/highlighted region on the original page/i),
    ).toBeInTheDocument();

    await user.click(within(source).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog", { name: "Source" })).not.toBeInTheDocument();
  });

  it("renders pending actions and source documents", () => {
    render(<Dashboard data={summary} />);

    expect(screen.getByText("R/V after 2 weeks")).toBeInTheDocument();
    expect(screen.getByText(/Review/)).toBeInTheDocument();
    expect(screen.getByText("Lab report")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Open Lab report from/ })).toBeInTheDocument();
  });

  it("does not flash empty panels while the summary loads", () => {
    render(<Dashboard patient={summary.patient} loading />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading summary…");
    expect(screen.queryByText("No results recorded.")).not.toBeInTheDocument();
    expect(screen.queryByText("No source documents.")).not.toBeInTheDocument();
  });
});
