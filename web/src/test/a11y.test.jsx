import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { describe, expect, it } from "vitest";
import Dashboard from "../pages/Dashboard";
import summary from "../fixtures/summary.json";

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
