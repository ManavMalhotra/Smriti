import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import History, { buildHistory } from "../components/History";

function report(overrides = {}) {
  return {
    id: "r-1",
    document_id: "d-1",
    category: "lab",
    report_date: "2025-11-02",
    facility_name: "City Lab",
    title: "City Lab",
    summary: "HbA1c 8.9 %",
    page_start: 1,
    page_end: 1,
    status: "auto",
    review_count: 0,
    facts: [],
    ...overrides,
  };
}

function document(overrides = {}) {
  return {
    id: "d-1",
    doc_type: "lab_report",
    doc_date: "2025-11-02",
    collection_date: "2025-11-02",
    registration_date: null,
    facility_name: "City Lab",
    page_count: 1,
    status: "done",
    review_count: 0,
    ...overrides,
  };
}

describe("buildHistory", () => {
  it("orders records newest first", () => {
    const entries = buildHistory(
      [report({ id: "old", report_date: "2024-01-05" }), report({ id: "new", report_date: "2025-06-01" })],
      [],
    );
    expect(entries.map((entry) => entry.date)).toEqual(["2025-06-01", "2024-01-05"]);
  });

  it("includes documents that have no report, without duplicating covered ones", () => {
    const entries = buildHistory(
      [report()],
      [document(), document({ id: "d-2", doc_type: "prescription", collection_date: "2025-01-09" })],
    );
    expect(entries).toHaveLength(2);
    expect(entries.map((entry) => entry.documentId)).toEqual(["d-1", "d-2"]);
    expect(entries[1].title).toBe("Prescription");
  });

  it("sorts undated records last", () => {
    const entries = buildHistory(
      [report({ report_date: null })],
      [document({ id: "d-9", collection_date: null, doc_date: null })],
    );
    expect(entries.every((entry) => entry.date === null)).toBe(true);
  });
});

describe("History", () => {
  it("shows the newest record with its source action", async () => {
    const onOpen = vi.fn();
    const user = userEvent.setup();
    render(<History reports={[report()]} documents={[]} onOpen={onOpen} />);
    expect(screen.getByRole("heading", { name: "History" })).toBeInTheDocument();
    expect(screen.getByText("HbA1c 8.9 %")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Open City Lab from/ }));
    expect(onOpen).toHaveBeenCalledWith("d-1", 1);
  });

  it("collapses long histories and reveals them on request", async () => {
    const user = userEvent.setup();
    const reports = Array.from({ length: 12 }, (_, index) =>
      report({ id: `r-${index}`, document_id: `d-${index}`, summary: `Note ${index}` }),
    );
    render(<History reports={reports} documents={[]} />);
    expect(screen.getByRole("button", { name: "Show all 12" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show all 12" }));
    expect(screen.getByRole("button", { name: "Show recent" })).toHaveAttribute("aria-expanded", "true");
  });

  it("reports an empty history without inventing records", () => {
    render(<History reports={[]} documents={[]} />);
    expect(screen.getByText("No records yet.")).toBeInTheDocument();
  });
});
