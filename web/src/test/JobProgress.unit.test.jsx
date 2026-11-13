import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { afterEach, describe, expect, it, vi } from "vitest";
import JobProgress from "../components/JobProgress";

const reading = {
  id: "job-1", state: "running", page: 2, total: 2, stage: "qwen",
  model: "vlm:qwen3-vl-4b@q4_k_m+cuda", current_page: 1,
  completed_pages: 0, stage_total: 2,
  events: [{ sequence: 1, timestamp: "2026-11-04T10:00:00Z", event: "qwen_reading", stage: "qwen", level: "info", message: "Qwen3-VL is reading page independently", model: "synthetic-model", page: 1 }],
};

afterEach(() => vi.useRealTimers());

describe("JobProgress", () => {
  it("shows one support ID, degraded logging, and a failure outside retained history", async () => {
    const user = userEvent.setup();
    const { container } = render(<JobProgress job={{ ...reading, support_id: "job-1", logging: { file: { available: false, degraded: true }, terminal: { available: true, degraded: false } }, latest_failure: { sequence: 0, message: "Source preparation failed" }, events_truncated: 12 }} />);
    await user.click(screen.getByText("Processing details"));
    expect(screen.getByText("Support ID job-1")).toBeInTheDocument();
    expect(screen.getByText(/Local diagnostic logging is degraded/)).toBeInTheDocument();
    expect(screen.getByText("Latest failure: Source preparation failed")).toBeInTheDocument();
    expect(screen.getByText(/12 earlier events omitted/)).toBeInTheDocument();
    expect(await axe(container)).toHaveNoViolations();
  });
  it("names the current GLM-OCR engine and keeps historical Qwen jobs readable", () => {
    const current = render(<JobProgress job={{ ...reading, model: "vlm:glm-ocr-0.9b@q8_0+cuda" }} />);
    expect(screen.getByText("GLM-OCR 0.9B")).toBeInTheDocument();
    current.unmount();
    render(<JobProgress job={reading} />);
    expect(screen.getByText("Qwen3-VL 4B")).toBeInTheDocument();
  });

  it("shows model-specific progress, not overall OCR completion", async () => {
    const user = userEvent.setup();
    const { container } = render(<JobProgress job={reading} />);
    expect(screen.getByRole("status")).toHaveTextContent("reading page independently");
    const progress = screen.getByRole("progressbar");
    expect(progress).toHaveAttribute("value", "0");
    expect(progress).toHaveAttribute("max", "2");
    expect(screen.getByText("Qwen3-VL 4B")).toBeInTheDocument();
    await user.click(screen.getByText("Processing details"));
    expect(screen.getByText("synthetic-model")).toBeVisible();
    expect(screen.getByText("Activity")).toBeVisible();
    expect(await axe(container)).toHaveNoViolations();
  });

  it("does not fabricate progress for old jobs or unknown stages", () => {
    const { rerender } = render(<JobProgress job={{ state: "running", page: 2, total: 2 }} />);
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.getByText("Detailed history is unavailable for this job.")).toBeInTheDocument();
    rerender(<JobProgress job={{ ...reading, stage: "saving", current_page: null, completed_pages: null, stage_total: null, events: [] }} />);
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("keeps skipped verification and truncation explicit", async () => {
    const user = userEvent.setup();
    render(<JobProgress job={{ state: "done", stage: "done", events_truncated: 3, events: [{ sequence: 4, event: "qwen_disabled", timestamp: "2026-11-04T10:00:00Z", level: "warning", stage: "extraction", message: "Qwen3-VL disabled; no independent model verification" }] }} />);
    expect(screen.getByText("Skipped")).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    await user.click(screen.getByText("Processing details"));
    expect(screen.getByText(/3 earlier events omitted/)).toBeVisible();
    expect(screen.getByText("Warning")).toBeVisible();
  });

  it("freezes elapsed time when a job finishes", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-11-04T10:00:10Z"));
    const { rerender } = render(<JobProgress job={{ ...reading, started_at: "2026-11-04T10:00:00Z" }} />);
    expect(screen.getByLabelText("Elapsed 10s")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(2000));
    expect(screen.getByLabelText("Elapsed 12s")).toBeInTheDocument();
    rerender(<JobProgress job={{ ...reading, state: "done", stage: "done", elapsed_seconds: 12, finished_at: "2026-11-04T10:00:12Z" }} />);
    act(() => vi.advanceTimersByTime(60000));
    expect(screen.getByLabelText("Elapsed 12s")).toBeInTheDocument();
  });

  it("uses durable verification status after history truncation and ignores prior attempts", () => {
    const { rerender } = render(<JobProgress job={{ state: "done", stage: "done", verification_state: "skipped", events_truncated: 501, events: [] }} />);
    expect(screen.getByText("Skipped")).toBeInTheDocument();
    rerender(<JobProgress job={{ state: "running", stage: "qwen", events: [{ sequence: 1, event: "qwen_disabled" }, { sequence: 2, event: "started" }] }} />);
    expect(screen.queryByText("Skipped")).not.toBeInTheDocument();
    rerender(<JobProgress job={{ state: "done", stage: "done", verification_state: "partial", events: [] }} />);
    expect(screen.getByText("Partial; review required")).toBeInTheDocument();
    rerender(<JobProgress job={{ state: "running", stage: "qwen", verification_state: "partial", completed_pages: 2, stage_total: 59, events: [] }} />);
    expect(screen.getByText("2 / 59 eligible pages resolved")).toBeInTheDocument();
    rerender(<JobProgress job={{ state: "done", stage: "done", verification_state: "unavailable", events: [] }} />);
    expect(screen.getByText("OCR-only; review required")).toBeInTheDocument();
  });

  it("shows failed inference context rather than the later cleanup stage", () => {
    render(<JobProgress job={{ state: "failed", stage: "cleanup", failure_context: { stage: "qwen", model: "synthetic-vlm", current_page: 2 }, total: 3, events: [] }} />);
    expect(screen.getByText("Source page 2 of 3")).toBeInTheDocument();
    expect(screen.getByText("synthetic-vlm")).toBeInTheDocument();
    expect(screen.getByText("Failed").closest("li")).toHaveTextContent("Verify");
    expect(screen.getByText("Not reached").closest("li")).toHaveTextContent("Save");
  });

  it("keeps source position separate from eligible-page completion and shows safe HTTP evidence", () => {
    const { rerender } = render(<JobProgress job={{ ...reading, current_page: 3, total: 73, completed_pages: 2, stage_total: 59 }} />);
    expect(screen.getByText("Source page 3 of 73")).toBeInTheDocument();
    expect(screen.getByText("2 / 59 eligible pages read")).toBeInTheDocument();
    rerender(<JobProgress job={{ state: "failed", total: 73, failure_context: { stage: "qwen", current_page: 3, code: "qwen_http_error", status: 400 } }} />);
    expect(screen.getByText("qwen_http_error")).toBeInTheDocument();
    expect(screen.getByText("HTTP 400")).toBeInTheDocument();
  });
});
