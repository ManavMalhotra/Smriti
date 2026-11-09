import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import Processing from "../components/Processing";

const running = {
  id: "j-1",
  state: "running",
  stage: "qwen",
  current_page: 3,
  total: 9,
  started_at: "2026-11-09T10:00:00Z",
  events: [
    {
      sequence: 1,
      event: "qwen_reading",
      level: "info",
      stage: "qwen",
      message: "Qwen3-VL is reading page independently",
      timestamp: "2026-11-09T10:00:01Z",
      page: 3,
    },
  ],
};

describe("Processing", () => {
  it("renders nothing while no document is in flight", () => {
    const { container } = render(<Processing jobs={[]} onQueue={() => {}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the live stage of each in-flight document", () => {
    render(<Processing jobs={[running]} onQueue={() => {}} />);
    expect(screen.getByRole("heading", { name: "Processing" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Qwen3-VL is reading page independently",
    );
    expect(screen.getByText("Source page 3 of 9")).toBeInTheDocument();
  });

  it("opens the queue when the document count is activated", async () => {
    const onQueue = vi.fn();
    const user = userEvent.setup();
    render(<Processing jobs={[running]} onQueue={onQueue} />);
    await user.click(screen.getByRole("button", { name: "1 document" }));
    expect(onQueue).toHaveBeenCalledTimes(1);
  });
});
