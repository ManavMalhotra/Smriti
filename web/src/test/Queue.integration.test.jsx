import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { axe } from "jest-axe";
import { afterEach, describe, expect, it, vi } from "vitest";
import Queue from "../pages/Queue";

const pending = { id: "pending-1", state: "queued", stage: "pending_intake", document_id: null, total: null };
const reading = { id: "reading-1", state: "running", document_id: "document-1", total: 73, stage: "qwen", current_page: 3, completed_pages: 2, stage_total: 59, activity: "Qwen3-VL is reading page independently" };
const props = { patient: { id: "p-1" }, onDone: vi.fn(), onAdd: vi.fn(), onOpenDocument: vi.fn(), onSignOut: vi.fn() };
const response = (data, status = 200) => ({ ok: status === 200, status, json: async () => data });

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("Queue", () => {
  it("loads server jobs, keeps unknown totals unknown, and is accessible", async () => {
    const fetch = vi.fn().mockResolvedValue(response({ jobs: [pending, reading], has_more: false }));
    vi.stubGlobal("fetch", fetch);
    const { container } = render(<Queue {...props} />);
    await screen.findByText("Source page 3 of 73");
    expect(screen.getByText("2 / 59 eligible pages read")).toBeInTheDocument();
    expect(screen.getByText("Qwen3-VL is reading page independently")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Open document" })).toHaveLength(1);
    expect(fetch).toHaveBeenCalledWith("/api/jobs?scope=all&limit=20&offset=0", expect.objectContaining({ credentials: "same-origin" }));
    expect(await axe(container)).toHaveNoViolations();
  });

  it("loads full history only for the selected job and stops detail polling when terminal", async () => {
    vi.useFakeTimers();
    const fetch = vi.fn((url) => Promise.resolve(response(url.includes("?")
      ? { jobs: [pending, reading], has_more: false }
      : { ...reading, state: "failed", failure_context: { stage: "qwen", current_page: 3, code: "qwen_http_error", status: 400 }, events: [] })));
    vi.stubGlobal("fetch", fetch);
    render(<Queue {...props} />);
    await act(async () => {});
    const region = screen.getByRole("region", { name: "Document document-1" });
    fireEvent.click(within(region).getByRole("button", { name: "Show details" }));
    await act(async () => {});
    expect(within(region).getByText("HTTP 400")).toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
    expect(fetch.mock.calls.filter(([url]) => url === "/api/jobs/reading-1")).toHaveLength(1);
    expect(fetch.mock.calls.some(([url]) => url === "/api/jobs/pending-1")).toBe(false);
  });

  it("does not overlap list requests and aborts them when unmounted", async () => {
    vi.useFakeTimers();
    let resolve;
    const fetch = vi.fn(() => new Promise((done) => { resolve = done; }));
    vi.stubGlobal("fetch", fetch);
    const { unmount } = render(<Queue {...props} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(fetch).toHaveBeenCalledOnce();
    const signal = fetch.mock.calls[0][1].signal;
    unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => { resolve(response({ jobs: [reading], has_more: false })); });
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("retains last progress on connection failure and stops after session expiry", async () => {
    vi.useFakeTimers();
    const fetch = vi.fn()
      .mockResolvedValueOnce(response({ jobs: [reading], has_more: false }))
      .mockRejectedValueOnce(new Error("connection"))
      .mockResolvedValue(response({}, 401));
    vi.stubGlobal("fetch", fetch);
    render(<Queue {...props} />);
    await act(async () => {});
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(screen.getByText("Source page 3 of 73")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Connection interrupted");
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(screen.getByRole("alert")).toHaveTextContent("session expired");
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it("separates recent history, paginates it, and leaves terminal listings idle", async () => {
    vi.useFakeTimers();
    const fetch = vi.fn().mockResolvedValue(response({ jobs: [reading], has_more: true }));
    vi.stubGlobal("fetch", fetch);
    render(<Queue {...props} />);
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: "Finished" }));
    await act(async () => {});
    expect(fetch.mock.calls.at(-1)[0]).toBe("/api/jobs?scope=recent&limit=20&offset=0");
    fireEvent.click(screen.getByRole("button", { name: "Finished" }));
    expect(screen.getByText("Source page 3 of 73")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await act(async () => {});
    expect(fetch.mock.calls.at(-1)[0]).toBe("/api/jobs?scope=recent&limit=20&offset=20");
    const calls = fetch.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(fetch).toHaveBeenCalledTimes(calls);
  });

  it("moves completed jobs from Active to Recent on the next list read", async () => {
    vi.useFakeTimers();
    let completed = false;
    const fetch = vi.fn((url) => Promise.resolve(response({
      jobs: url.includes("scope=recent") ? [{ ...reading, state: "done", stage: "done" }] : completed ? [] : [reading],
      has_more: false,
    })));
    vi.stubGlobal("fetch", fetch);
    render(<Queue {...props} />);
    await act(async () => {});
    fireEvent.click(screen.getByRole("button", { name: "Active" }));
    await act(async () => {});
    completed = true;
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(screen.getByText("No active jobs.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Finished" }));
    await act(async () => {});
    expect(screen.getByRole("button", { name: "Review extracted fields" })).toBeInTheDocument();
  });

  it("offers manual refresh after a recent-history connection failure", async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(response({ jobs: [], has_more: false }))
      .mockRejectedValueOnce(new Error("connection"))
      .mockResolvedValue(response({ jobs: [reading], has_more: false }));
    vi.stubGlobal("fetch", fetch);
    render(<Queue {...props} />);
    await screen.findByText("No uploaded jobs.");
    fireEvent.click(screen.getByRole("button", { name: "Finished" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Refresh to try again");
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByText("Source page 3 of 73");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows failed uploads by default and retries their stored document without re-uploading", async () => {
    let retried = false;
    const fetch = vi.fn((url) => {
      if (url === "/api/jobs/reading-1/retry") {
        retried = true;
        return Promise.resolve(response({ id: reading.id, state: "queued" }));
      }
      return Promise.resolve(response({ jobs: [{ ...reading, state: retried ? "queued" : "failed", stage: retried ? "queued" : "ocr" }], has_more: false }));
    });
    vi.stubGlobal("fetch", fetch);
    render(<Queue {...props} />);
    expect(await screen.findByRole("button", { name: "Retry" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Failed", pressed: false }));
    await act(async () => {});
    expect(fetch.mock.calls.at(-1)[0]).toBe("/api/jobs?scope=failed&limit=20&offset=0");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await act(async () => {});
    expect(fetch).toHaveBeenCalledWith("/api/jobs/reading-1/retry", expect.objectContaining({ method: "POST" }));
    expect(screen.getByRole("button", { name: "All", pressed: true })).toBeInTheDocument();
  });
});
