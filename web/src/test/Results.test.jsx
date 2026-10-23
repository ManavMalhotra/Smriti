import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Results from "../components/Results";
import summary from "../fixtures/summary.json";

const result = {
  ...summary.results[0],
  excluded: [
    {
      document_id: "d-02",
      reason: "Value outside plausible range",
    },
  ],
};

describe("Results", () => {
  it("shows the value, unit, reference range, and printed flag", () => {
    render(<Results results={[result]} />);

    expect(screen.getByText("8.9")).toBeInTheDocument();
    expect(screen.getByText("4–5.6")).toBeInTheDocument();
    expect(screen.getAllByText("%")).toHaveLength(2);
    expect(screen.getByText("H")).toBeInTheDocument();
    expect(
      screen.getByText("Flags are shown exactly as printed on the source document."),
    ).toBeInTheDocument();
  });

  it("surfaces excluded readings with their source document", () => {
    render(<Results results={[result]} />);

    const notice = screen.getByRole("note");
    expect(notice).toHaveTextContent("Value outside plausible range");
    expect(notice).toHaveTextContent("d-02");
  });
});
