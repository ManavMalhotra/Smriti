import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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

  it("marks pending values and links the live source page", async () => {
    const pending = {
      ...result,
      excluded: [],
      points: [{ ...result.points[0], status: "review" }],
    };
    render(<Results results={[pending]} />);

    expect(screen.getByText("Review")).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent(
      "1 extracted value is awaiting review",
    );

    await userEvent.click(
      screen.getByRole("button", { name: /open source for hba1c/i }),
    );
    expect(screen.getByRole("img", { name: "Source page 1" })).toBeInTheDocument();
  });

  it("closes the source dialog with Escape", async () => {
    const user = userEvent.setup();
    render(<Results results={[result]} />);

    await user.click(
      screen.getByRole("button", { name: /open source for hba1c/i }),
    );
    expect(screen.getByRole("dialog", { name: "Source" })).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Source" })).not.toBeInTheDocument();
  });

  it("surfaces excluded readings with their source document", () => {
    render(<Results results={[result]} />);

    const notice = screen.getByRole("note");
    expect(notice).toHaveTextContent("Value outside plausible range");
    expect(notice).toHaveTextContent("d-02");
  });
});
