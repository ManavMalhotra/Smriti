import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { describe, expect, it, vi } from "vitest";
import StandardizedSummary from "../components/StandardizedSummary";

const sourceSummary = {
  year_wise_history: [
    { title: "Blood test", summary: "CBC report", exact_date: "2026-09-14", source_doc_id: "doc-2", source_page: 3, status: "review" },
    { title: "Clinic note", summary: null, exact_date: null, source_doc_id: "doc-1", source_page: 1, status: "auto" },
  ],
};

describe("Recent reports", () => {
  it("shows source-linked report summaries and review status", async () => {
    const onOpenDocument = vi.fn();
    const { container } = render(<main><StandardizedSummary summary={sourceSummary} onOpenDocument={onOpenDocument} /></main>);
    expect(screen.getByRole("heading", { name: "Recent reports" })).toBeInTheDocument();
    expect(screen.getByText("Blood test")).toBeInTheDocument();
    expect(screen.getByText("Needs review")).toBeInTheDocument();
    expect(screen.getByText("CBC report")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Open source · page 3" }));
    expect(onOpenDocument).toHaveBeenCalledWith("doc-2", 3);
    expect(screen.queryByRole("button", { name: /Gemini|Cloud/i })).not.toBeInTheDocument();
    expect(await axe(container)).toHaveNoViolations();
  });
});
