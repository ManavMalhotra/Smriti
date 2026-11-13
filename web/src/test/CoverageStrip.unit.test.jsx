import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import CoverageStrip from "../components/CoverageStrip";
import summary from "../fixtures/summary.json";

describe("CoverageStrip", () => {
  it("renders one cell per quarter and marks empty quarters", () => {
    render(<CoverageStrip coverage={summary.coverage} />);

    const cells = screen.getAllByRole("listitem");
    expect(cells).toHaveLength(3);

    expect(cells[0]).toHaveTextContent("2025 Q4");
    expect(cells[0]).toHaveTextContent("1 document");
    expect(cells[1]).toHaveTextContent("2026 Q1");
    expect(cells[1]).toHaveTextContent("0 documents");
    expect(cells[1]).toHaveAttribute("data-docs", "0");
    expect(cells[2]).toHaveTextContent("2026 Q3");
    expect(cells[2]).toHaveTextContent("1 document");

    expect(screen.getByText("2 dated documents")).toBeInTheDocument();
  });
});
