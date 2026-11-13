import { act, fireEvent, render, screen } from "@testing-library/react";
import { axe } from "jest-axe";
import { afterEach, describe, expect, it, vi } from "vitest";
import DocumentsLibrary from "../pages/DocumentsLibrary";

const props = { patient: { id: "p-1", alias: "Synthetic patient" }, onOpenDocument: vi.fn(), onQueue: vi.fn(), onAdd: vi.fn() };
const failed = { id: "d-1", document_id: "d-1", job_id: "j-1", job_state: "failed", status: "failed",
  display_name: "Synthetic report", doc_type: "lab_report", page_count: 16, review_count: 0, retryable: true };
const pending = { id: "j-2", document_id: null, job_id: "j-2", job_state: "queued", status: "pending_intake", page_count: null, retryable: false };
const response = (data, status = 200) => ({ ok: status === 200, status, json: async () => data });

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.clearAllMocks(); });

describe("Documents library", () => {
  it("loads uploads independently of the dashboard and shows failures and pending preparation", async () => {
    const fetch = vi.fn().mockResolvedValue(response({ documents: [failed, pending], has_more: false }));
    vi.stubGlobal("fetch", fetch);
    const { container } = render(<DocumentsLibrary {...props} />);
    await screen.findByText("Synthetic report");
    expect(screen.getByText("16 pages")).toBeInTheDocument();
    expect(screen.getByText("Pages not yet inspected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry processing" })).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith("/api/documents?limit=20&offset=0&filter=All", expect.objectContaining({ credentials: "same-origin" }));
    fireEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(props.onOpenDocument).toHaveBeenCalledWith("d-1");
    fireEvent.click(screen.getByRole("button", { name: "View upload in Queue" }));
    expect(props.onQueue).toHaveBeenCalledOnce();
    expect(await axe(container)).toHaveNoViolations();
  });

  it("retries the existing job and refreshes status rather than uploading another file", async () => {
    let retried = false;
    const fetch = vi.fn((url) => {
      if (url === "/api/jobs/j-1/retry") {
        retried = true;
        return Promise.resolve(response({ state: "queued" }));
      }
      return Promise.resolve(response({ documents: [{ ...failed, job_state: retried ? "queued" : "failed", status: retried ? "queued" : "failed", retryable: !retried }], has_more: false }));
    });
    vi.stubGlobal("fetch", fetch);
    render(<DocumentsLibrary {...props} />);
    fireEvent.click(await screen.findByRole("button", { name: "Retry processing" }));
    await screen.findByText("Queued");
    expect(fetch).toHaveBeenCalledWith("/api/jobs/j-1/retry", expect.objectContaining({ method: "POST" }));
    expect(screen.queryByRole("button", { name: "Retry processing" })).not.toBeInTheDocument();
    expect(fetch.mock.calls.every(([url, options]) => url !== "/api/documents" || options?.method !== "POST")).toBe(true);
  });

  it("paginates all stored uploads and offers refresh after a read error", async () => {
    const fetch = vi.fn().mockRejectedValueOnce(new Error("connection"))
      .mockResolvedValueOnce(response({ documents: [failed], has_more: true }))
      .mockResolvedValue(response({ documents: [{ ...failed, id: "d-2", document_id: "d-2", display_name: "Older upload" }], has_more: false }));
    vi.stubGlobal("fetch", fetch);
    render(<DocumentsLibrary {...props} />);
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await screen.findByText("Synthetic report");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("Older upload");
    expect(fetch.mock.calls.at(-1)[0]).toBe("/api/documents?limit=20&offset=20&filter=All");
    expect(screen.getByText("Page 2")).toBeInTheDocument();
  });

  it("requests filtered pages across the full library", async () => {
    const fetch = vi.fn((url) => Promise.resolve(response({ documents: url.includes("filter=Scans") ? [] : [failed], has_more: false })));
    vi.stubGlobal("fetch", fetch);
    render(<DocumentsLibrary {...props} />);
    await screen.findByText("Synthetic report");
    fireEvent.click(screen.getByRole("button", { name: "Scans & discharge" }));
    await screen.findByText("No documents match this filter.");
    expect(fetch.mock.calls.at(-1)[0]).toBe("/api/documents?limit=20&offset=0&filter=Scans%20%26%20discharge");
  });

  it("polls pending uploads without overlapping requests and stops on unmount", async () => {
    vi.useFakeTimers();
    let finish;
    const fetch = vi.fn(() => new Promise((resolve) => { finish = resolve; }));
    vi.stubGlobal("fetch", fetch);
    const { unmount } = render(<DocumentsLibrary {...props} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(fetch).toHaveBeenCalledOnce();
    await act(async () => { finish(response({ documents: [pending], has_more: false })); });
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(fetch).toHaveBeenCalledTimes(2);
    const signal = fetch.mock.calls.at(-1)[1].signal;
    unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => { finish(response({ documents: [failed], has_more: false })); });
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(fetch).toHaveBeenCalledTimes(2);
  });
});
