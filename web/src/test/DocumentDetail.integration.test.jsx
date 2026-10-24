import { render, screen, within } from "@testing-library/react";
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
      screen.getByRole("img", { name: "Page 1 of the Lab report" }),
    ).toBeInTheDocument();
    expect(screen.getByText("HbA1c")).toBeInTheDocument();
    expect(screen.getByText("8.9")).toBeInTheDocument();

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
});
