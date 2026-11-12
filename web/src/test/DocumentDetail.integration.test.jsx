import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import DocumentDetail from "../pages/DocumentDetail";

const patient = { id: "pat-1", alias: "P-02" };

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

function observation(overrides = {}) {
  return {
    id: "obs-1",
    analyte_id: "hba1c",
    label_raw: "HbA1c",
    value_num: "8.9",
    value_text: "8.9",
    unit_raw: "%",
    unit_norm: null,
    ref_low: "4",
    ref_high: "6",
    flag_printed: null,
    bbox: [0.1, 0.2, 0.3, 0.4],
    page: 1,
    engine: "fake",
    confidence: 0.98,
    status: "review",
    reason: "Extracted locally; review required.",
    mapping_rule: "exact",
    created_at: "2026-10-23T00:00:00Z",
    ...overrides,
  };
}

function detailResponse(overrides = {}) {
  return {
    id: "doc-1",
    patient_id: patient.id,
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
    observations: [observation()],
    medications: [],
    pages: [{ page: 1, url: "/api/documents/doc-1/page/1" }],
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DocumentDetail", () => {
  it("shows the page image, extracted field, and accepts a value", async () => {
    const onSummary = vi.fn();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(detailResponse()))
      .mockResolvedValueOnce(
        jsonResponse({
          observation: observation({
            status: "auto",
            reason: "Accepted during review.",
          }),
          summary: {},
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(
      <DocumentDetail
        documentId="doc-1"
        patient={patient}
        onBack={() => {}}
        onSummary={onSummary}
      />,
    );

    expect(
      await screen.findByRole("heading", { level: 1, name: "Document review" }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("img", { name: "Page 1 of the Lab report" }),
    ).toBeInTheDocument();
    expect(screen.getByText("HbA1c")).toBeInTheDocument();
    expect(screen.getByText("8.9")).toBeInTheDocument();
    expect(fetchMock.mock.calls[0][0]).toBe("/api/documents/doc-1?page=1&offset=0");

    const row = screen.getByRole("row", { name: /HbA1c/ });
    await user.click(within(row).getByRole("button", { name: "Accept" }));

    expect(await within(row).findByText("Accepted")).toBeInTheDocument();
    expect(onSummary).toHaveBeenCalledTimes(1);
    const [url, options] = fetchMock.mock.calls[1];
    expect(url).toBe("/api/observations/obs-1/review");
    expect(JSON.parse(options.body)).toEqual({ action: "accept" });
  });

  it("submits a corrected value and unit", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(detailResponse()))
      .mockResolvedValueOnce(
        jsonResponse({
          observation: observation({
            value_num: "9.1",
            value_text: "9.1",
            unit_norm: "%",
            status: "auto",
            reason: "Corrected during review.",
          }),
          summary: {},
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<DocumentDetail documentId="doc-1" patient={patient} onBack={() => {}} />);

    const row = await screen.findByRole("row", { name: /HbA1c/ });
    await user.click(within(row).getByRole("button", { name: "Correct" }));
    const value = within(row).getByLabelText("Value");
    await user.clear(value);
    await user.type(value, "9.1");
    await user.click(within(row).getByRole("button", { name: "Save" }));

    expect(await within(row).findByText("Accepted")).toBeInTheDocument();
    const [url, options] = fetchMock.mock.calls[1];
    expect(url).toBe("/api/observations/obs-1/review");
    expect(JSON.parse(options.body)).toEqual({
      action: "correct",
      value_num: "9.1",
      unit_norm: "%",
    });
  });

  it("corrects a text-only prose field", async () => {
    const prose = observation({
      analyte_id: null,
      label_raw: "Impression",
      value_num: null,
      value_text: "Normal CT brain.",
      unit_raw: null,
      ref_low: null,
      ref_high: null,
      fact_type: "impression",
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(detailResponse({ observations: [prose] })),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          observation: { ...prose, value_text: "No acute abnormality.", status: "auto" },
          summary: {},
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<DocumentDetail documentId="doc-1" patient={patient} onBack={() => {}} />);

    const row = await screen.findByRole("row", { name: /Impression/ });
    await user.click(within(row).getByRole("button", { name: "Correct" }));
    const value = within(row).getByLabelText("Value");
    await user.clear(value);
    await user.type(value, "No acute abnormality.");
    await user.click(within(row).getByRole("button", { name: "Save" }));

    const [url, options] = fetchMock.mock.calls[1];
    expect(url).toBe("/api/observations/obs-1/review");
    expect(JSON.parse(options.body)).toEqual({
      action: "correct",
      value_text: "No acute abnormality.",
      unit_norm: null,
    });
  });

  it("corrects report date, category, title, and facility", async () => {
    const report = {
      id: "r-1",
      category: "imaging",
      report_type: "ct",
      report_date: "2024-03-02",
      facility_name: "BESTB DIAGNOSTICS",
      title: "BESTB DIAGNOSTICS",
      summary: "Stable.",
      page_start: 1,
      page_end: 1,
      status: "auto",
      reason: null,
      model_version: "test",
      created_at: "2026-10-23T00:00:00Z",
      fact_count: 0,
      review_count: 0,
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(detailResponse({ reports: [report] })))
      .mockResolvedValueOnce(
        jsonResponse({
          report: {
            ...report,
            report_date: "2024-03-03",
            category: "lab",
            title: "CT chest",
            facility_name: "City Hospital",
          },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<DocumentDetail documentId="doc-1" patient={patient} onBack={() => {}} />);

    await screen.findByRole("heading", { name: "Reports in this document" });
    await user.click(
      screen.getByRole("button", { name: "Edit date and category" }),
    );
    const date = screen.getByLabelText("Date");
    await user.clear(date);
    await user.type(date, "2024-03-03");
    await user.selectOptions(screen.getByLabelText("Category"), "lab");
    const title = screen.getByLabelText("Title");
    await user.clear(title);
    await user.type(title, "CT chest");
    const facility = screen.getByLabelText("Facility");
    await user.clear(facility);
    await user.type(facility, "City Hospital");
    await user.click(screen.getByRole("button", { name: "Save report" }));

    const [url, options] = fetchMock.mock.calls[1];
    expect(url).toBe("/api/reports/r-1");
    expect(options.method).toBe("PATCH");
    expect(JSON.parse(options.body)).toEqual({
      report_date: "2024-03-03",
      category: "lab",
      title: "CT chest",
      facility_name: "City Hospital",
    });
    expect(await screen.findByText("CT chest")).toBeInTheDocument();
  });

  it("disables accept and correct for an unmapped field", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(
          detailResponse({
            observations: [
              observation({ analyte_id: null, label_raw: "Some assay" }),
            ],
          }),
        ),
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<DocumentDetail documentId="doc-1" patient={patient} onBack={() => {}} />);

    const row = await screen.findByRole("row", { name: /Some assay/ });
    expect(
      within(row).getByText("Not linked to a standard test; reject only."),
    ).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "Accept" })).toBeDisabled();
    expect(within(row).getByRole("button", { name: "Correct" })).toBeDisabled();
    expect(within(row).getByRole("button", { name: "Reject" })).toBeEnabled();
  });

  it("requests bounded source pages and result ranges without losing an edit", async () => {
    const fetchMock = vi.fn((url) => {
      const query = new URL(url, "http://localhost").searchParams;
      const page = Number(query.get("page"));
      return Promise.resolve(jsonResponse(detailResponse({
        page_count: 1001, detail_page: page, offset: Number(query.get("offset")), has_more: query.get("offset") === "0",
        pages: [{ page, url: `/api/documents/doc-1/page/${page}` }],
        observations: [observation({ page })],
      })));
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<DocumentDetail documentId="doc-1" patient={patient} initialPage={21} onBack={() => {}} />);
    await screen.findByRole("img", { name: "Page 21 of the Lab report" });
    await user.click(screen.getByRole("button", { name: "Next results" }));
    expect(fetchMock.mock.calls.at(-1)[0]).toBe("/api/documents/doc-1?page=21&offset=100");
    await screen.findByRole("button", { name: "Previous results" });
    await user.click(screen.getByRole("button", { name: "Next page" }));
    await screen.findByRole("img", { name: "Page 22 of the Lab report" });
    expect(fetchMock.mock.calls.at(-1)[0]).toBe("/api/documents/doc-1?page=22&offset=0");
    await user.click(screen.getByRole("button", { name: "Correct" }));
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next results" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.change(screen.getByLabelText("Page"), { target: { value: "1001" } });
    await screen.findByRole("img", { name: "Page 1001 of the Lab report" });
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
  });

  it("aborts an old account's detail request and ignores its late response", async () => {
    let resolveOld;
    const old = new Promise((resolve) => { resolveOld = resolve; });
    const fetchMock = vi.fn().mockReturnValueOnce(old).mockResolvedValue(jsonResponse(detailResponse({ observations: [], page_text: [] })));
    vi.stubGlobal("fetch", fetchMock);
    const { rerender, unmount } = render(<DocumentDetail documentId="doc-1" patient={patient} onBack={() => {}} />);
    rerender(<DocumentDetail documentId="doc-2" patient={{ id: "other", alias: "Other" }} onBack={() => {}} />);
    expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(true);
    await act(async () => resolveOld(jsonResponse(detailResponse())));
    expect(screen.queryByText("HbA1c")).not.toBeInTheDocument();
    unmount();
    expect(fetchMock.mock.calls.at(-1)[1].signal.aborted).toBe(true);
  });
});
