import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { afterEach, describe, expect, it, vi } from "vitest";
import Dashboard from "../pages/Dashboard";
import DocumentDetail from "../pages/DocumentDetail";
import summary from "../fixtures/summary.json";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Dashboard accessibility", () => {
  it("has no automatically detectable violations", async () => {
    const { container } = render(<Dashboard data={summary} />);

    expect(await axe(container)).toHaveNoViolations();
  });

  it("has no automatically detectable violations with a source open", async () => {
    const user = userEvent.setup();
    const { container } = render(<Dashboard data={summary} />);

    await user.click(
      screen.getByRole("button", { name: /open source for hba1c/i }),
    );

    expect(await axe(container)).toHaveNoViolations();
  });
});

describe("Document review accessibility", () => {
  it("has no automatically detectable violations", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({
          id: "doc-1",
          patient_id: "p-01",
          doc_type: "lab_report",
          capture_type: "printed",
          doc_date: "2025-11-02",
          collection_date: "2025-11-02",
          page_count: 1,
          status: "done",
          page_text: [{ page: 1, text: "HbA1c 8.9 %", engine: "fake" }],
          observations: [
            {
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
            },
          ],
          medications: [],
          pages: [{ page: 1, url: "/api/documents/doc-1/page/1" }],
        }),
      }),
    );
    const { container } = render(
      <DocumentDetail documentId="doc-1" patient={summary.patient} onBack={() => {}} />,
    );

    await screen.findByRole("heading", { level: 1, name: "Document review" });

    expect(await axe(container)).toHaveNoViolations();
  });
});
