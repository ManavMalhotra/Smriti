import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import App from "../App";
import Dashboard from "../pages/Dashboard";
import summary from "../fixtures/summary.json";

describe("App navigation", () => {
  it("opens the intake form and returns to the summary", async () => {
    const user = userEvent.setup();
    render(<App />);

    expect(screen.getByRole("heading", { level: 1, name: "P-01" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Add document" }));
    expect(
      screen.getByRole("heading", { level: 1, name: "Add a document" }),
    ).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Back to summary" }));
    expect(screen.getByRole("heading", { level: 1, name: "P-01" })).toHaveFocus();
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
