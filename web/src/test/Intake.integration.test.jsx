import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { afterEach, describe, expect, it, vi } from "vitest";
import Intake from "../pages/Intake";

const patient = { id: "pat-1", alias: "P-02", sex: "F" };

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

function uploadResponse(overrides = {}) {
  return jsonResponse(
    {
      document_id: "doc-1",
      job_id: "job-1",
      pages: 1,
      status: "queued",
      ...overrides,
    },
    202,
  );
}

function detailResponse(overrides = {}) {
  return jsonResponse({
    id: "doc-1",
    patient_id: patient.id,
    doc_type: "lab_report",
    doc_type_confidence: 0.9,
    capture_type: "printed",
    doc_date: null,
    collection_date: null,
    lab_name: null,
    page_count: 1,
    quality_score: 0.8,
    status: "done",
    processed_at: "2026-10-23T00:00:00Z",
    created_at: "2026-10-23T00:00:00Z",
    consent: null,
    egress: [],
    page_text: [{ page: 1, text: "HbA1c 8.9 %", engine: "fake" }],
    observations: [
      {
        id: "obs-1",
        analyte_id: "hba1c",
        label_raw: "HbA1c",
        value_num: "8.9",
        value_text: "8.9",
        unit_raw: "%",
        unit_norm: null,
        ref_low: "4",
        ref_high: "6",
        flag_printed: null,
        bbox: [0.1, 0.2, 0.3, 0.4],
        page: 1,
        engine: "fake",
        confidence: 0.98,
        status: "review",
        reason: "Extracted locally; review required.",
        mapping_rule: "exact",
        created_at: "2026-10-23T00:00:00Z",
      },
    ],
    medications: [],
    pages: [{ page: 1, url: "/api/documents/doc-1/page/1" }],
    ...overrides,
  });
}

async function fillForm(user, { type = "auto" } = {}) {
  await user.upload(
    screen.getByLabelText("Document file"),
    new File(["image"], "labs.png", { type: "image/png" }),
  );
  if (type !== "auto") {
    await user.selectOptions(screen.getByLabelText("Document type"), type);
  }
  fireEvent.change(screen.getByLabelText("Document date"), {
    target: { value: "2025-11-02" },
  });
  await user.click(screen.getByLabelText(/permission to store/i));
}

async function submit(user) {
  await user.click(screen.getByRole("button", { name: "Upload document" }));
}

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

async function selectBatch(user, names = ["one.png", "two.png"]) {
  await user.upload(screen.getByLabelText("Document file"), names.map((name, index) => new File([`image-${index}`], name, { type: "image/png" })));
  await user.click(screen.getByLabelText(/permission to store/i));
}

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Intake", () => {
  it("keeps a duplicate's existing job link so its failure remains visible", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse({ duplicate: true, document_id: "existing",
      job_id: "existing-job", status: "promoted", page_count: 16 }, 409))
      .mockResolvedValue(jsonResponse({ id: "existing-job", document_id: "existing", state: "failed", stage: "ocr", total_pages: 16, events: [] }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const onOpenDocument = vi.fn();
    render(<Intake patient={patient} onDone={() => {}} onOpenDocument={onOpenDocument} />);
    await fillForm(user);
    await submit(user);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/jobs/existing-job", expect.objectContaining({ credentials: "same-origin" })));
    await user.click(screen.getByRole("button", { name: "Open document" }));
    expect(onOpenDocument).toHaveBeenCalledWith("existing");
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/documents")).toHaveLength(1);
  });

  it("requires a file and consent before calling the API", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<Intake patient={patient} onDone={() => {}} />);

    await submit(user);
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a document file.");

    await user.upload(
      screen.getByLabelText("Document file"),
      new File(["image"], "labs.png", { type: "image/png" }),
    );
    await submit(user);
    expect(screen.getByRole("alert")).toHaveTextContent("Confirm consent before uploading.");

    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("Patient alias")).not.toBeInTheDocument();
    expect(screen.getByText(/documents for P-02/)).toBeInTheDocument();
  });

  it("uploads with automatic type detection and shows the queued page", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(uploadResponse())
      .mockResolvedValueOnce(
        jsonResponse({ id: "job-1", state: "running", page: 1, total: 1, error: null }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<Intake patient={patient} onDone={() => {}} />);

    await fillForm(user);
    await submit(user);

    expect(await screen.findByRole("heading", { name: "Document queued" })).toHaveFocus();
    expect(screen.getByRole("img", { name: /first page of the uploaded document/i })).toHaveAttribute(
      "src",
      "/api/documents/doc-1/page/1",
    );
    expect(screen.getByText("Detecting…")).toBeInTheDocument();

    const [uploadCall] = fetchMock.mock.calls;
    expect(uploadCall[0]).toBe("/api/documents");
    const body = uploadCall[1].body;
    expect(body).toBeInstanceOf(FormData);
    expect(body.get("patient_id")).toBe("pat-1");
    expect(body.get("doc_type")).toBeNull();
    expect(body.get("consent_scope")).toBe("local");
    expect(body.get("doc_date")).toBe("2025-11-02");
    expect(body.get("file").name).toBe("labs.png");
  });

  it("adopts the promoted document without downloading detail at completion", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(uploadResponse({ document_id: null, pages: null, status: "pending_intake" }))
      .mockResolvedValueOnce(
        jsonResponse({ id: "job-1", document_id: "promoted", state: "done", page: 39, total_pages: 39, error: null }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const onOpenDocument = vi.fn();
    render(<Intake patient={patient} onDone={() => {}} onOpenDocument={onOpenDocument} />);

    await fillForm(user, { type: "lab_report" });
    await submit(user);

    expect(await screen.findByRole("heading", { name: "Document processed" })).toHaveFocus();
    expect(screen.getByText("Lab report")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAttribute("src", "/api/documents/promoted/page/1");
    await user.click(screen.getByRole("button", { name: "Review extracted fields" }));
    expect(onOpenDocument).toHaveBeenCalledWith("promoted");
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/documents",
      "/api/jobs/job-1",
    ]);
  });

  it("reports a failed extraction instead of leaving the document queued", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(uploadResponse())
      .mockResolvedValueOnce(
        jsonResponse({
          id: "job-1",
          state: "failed",
          page: 1,
          total: 1,
          error: "OCR could not read this page.",
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<Intake patient={patient} onDone={() => {}} />);

    await fillForm(user);
    await submit(user);

    expect(
      await screen.findByRole("heading", { name: "Extraction failed" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("OCR could not read this page.");
    expect(
      screen.getByText("The document is stored, but local extraction failed."),
    ).toBeInTheDocument();
  });

  it("keeps the file and allows a retry after a server rejection", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(
          { error: { code: "rejected_quality", message: "Image is too blurry.", field: "file" } },
          422,
        ),
      )
      .mockResolvedValueOnce(uploadResponse({ document_id: "doc-2", job_id: "job-2" }))
      .mockResolvedValueOnce(
        jsonResponse({ id: "job-2", state: "running", page: 1, total: 1, error: null }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<Intake patient={patient} onDone={() => {}} />);

    await fillForm(user);
    await submit(user);

    expect(await screen.findByRole("alert")).toHaveTextContent("Image is too blurry.");
    expect(screen.getByRole("heading", { name: "labs.png" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry upload" }));

    expect(await screen.findByRole("heading", { name: "Document queued" })).toHaveFocus();
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/documents")).toHaveLength(2);
  });

  it("reports a duplicate without adding another document", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse(
        {
          document_id: "doc-existing",
          status: "queued",
          duplicate: true,
          doc_type: "lab_report",
          page_count: 1,
        },
        409,
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<Intake patient={patient} onDone={() => {}} />);

    await fillForm(user);
    await submit(user);

    expect(await screen.findByRole("heading", { name: "Already stored" })).toHaveFocus();
    expect(screen.getByText(/matches a document already in your records/i)).toBeInTheDocument();
    expect(screen.getByText("doc-existing")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("allows another upload with the same signed-in patient", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(uploadResponse())
      .mockResolvedValueOnce(
        jsonResponse({ id: "job-1", state: "running", page: 1, total: 1, error: null }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<Intake patient={patient} onDone={() => {}} />);

    await fillForm(user);
    await submit(user);
    await screen.findByRole("heading", { name: "Document queued" });

    await user.click(screen.getByRole("button", { name: "Add another document" }));

    expect(screen.queryByLabelText("Patient alias")).not.toBeInTheDocument();
    expect(screen.getByText(/documents for P-02/)).toBeInTheDocument();
    expect(screen.getByLabelText("Document file").files).toHaveLength(0);
    await waitFor(() => expect(screen.getByLabelText("Document file")).toHaveFocus());
    expect(screen.getByLabelText("Document type")).toHaveValue("auto");
    expect(screen.getByLabelText("Document date")).toHaveValue("");
    expect(screen.getByLabelText(/permission to store/i)).not.toBeChecked();
  });

  it("has no automatically detectable accessibility violations", async () => {
    const { container } = render(<Intake patient={patient} onDone={() => {}} />);

    expect(await axe(container)).toHaveNoViolations();
  });

  it("does not claim a stored source after deferred preparation failure", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(uploadResponse({ document_id: null, pages: null, status: "pending_intake" }))
      .mockResolvedValueOnce(jsonResponse({ id: "job-1", state: "failed", error: "Source preparation failed.", document_id: null, total: null }));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<Intake patient={patient} onDone={() => {}} onOpenDocument={vi.fn()} />);
    await fillForm(user);
    await submit(user);
    expect(await screen.findByText("Source preparation failed. No document was created.")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open document" })).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("uploads sequentially without waiting for processing, even with identical names", async () => {
    const first = deferred();
    const second = deferred();
    const reading = deferred();
    const posts = [];
    const fetchMock = vi.fn((url, options) => {
      if (url === "/api/documents") {
        posts.push(options.body);
        return posts.length === 1 ? first.promise : second.promise;
      }
      return reading.promise;
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const { container } = render(<Intake patient={patient} onDone={() => {}} />);
    await selectBatch(user, ["same.png", "same.png"]);
    expect(screen.getAllByRole("button", { name: "Remove same.png" })).toHaveLength(2);
    expect(await axe(container)).toHaveNoViolations();
    const button = screen.getByRole("button", { name: "Upload 2 documents" });
    await user.dblClick(button);
    expect(posts).toHaveLength(1);
    expect(screen.getByText("Waiting to upload")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add more documents" })).toBeDisabled();
    expect(await axe(container)).toHaveNoViolations();
    await act(async () => first.resolve(uploadResponse()));
    expect(posts).toHaveLength(2);
    expect(posts[0].get("file")).not.toBe(posts[1].get("file"));
    expect(fetchMock.mock.calls.filter(([url]) => url.startsWith("/api/jobs/"))).toHaveLength(1);
    for (const body of posts) {
      expect(body.get("consent_scope")).toBe("local");
      expect(body.get("doc_type")).toBeNull();
      expect(body.get("doc_date")).toBeNull();
    }
    await act(async () => second.resolve(uploadResponse({ document_id: "doc-2", job_id: "job-2" })));
    expect(screen.getAllByRole("region", { name: /same\.png\s*\(file/ })).toHaveLength(2);
    expect(screen.getByText(/2 uploaded · 0 processed/)).toBeInTheDocument();
  });

  it("keeps mixed outcomes independent and retries only the rejected upload", async () => {
    let post = 0;
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const onOpenDocument = vi.fn();
    const fetchMock = vi.fn((url) => {
      if (url === "/api/documents") {
        post += 1;
        return Promise.resolve([
          uploadResponse(),
          jsonResponse({ error: { message: "Image too blurry." } }, 422),
          jsonResponse({ duplicate: true, document_id: "existing", status: "failed", page_count: 2 }, 409),
          uploadResponse({ document_id: "doc-4", job_id: "job-4" }),
          uploadResponse({ document_id: "doc-2", job_id: "job-2" }),
        ][post - 1]);
      }
      return Promise.resolve(jsonResponse({ id: url.split("/").at(-1), state: url.endsWith("job-4") ? "failed" : "done", error: url.endsWith("job-4") ? "Model timed out." : null, stage: "done", verification_state: "skipped", events: [{ sequence: 1, timestamp: "2026-11-04T10:00:00Z", level: "warning", message: "Independent verification skipped" }] }));
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const { container } = render(<Intake patient={patient} onDone={() => {}} onOpenDocument={onOpenDocument} />);
    await selectBatch(user, ["good.png", "blurry.png", "duplicate.png", "failed.png"]);
    await user.selectOptions(screen.getByLabelText("Document type"), "lab_report");
    fireEvent.change(screen.getByLabelText("Document date"), { target: { value: "2025-11-02" } });
    await user.click(screen.getByRole("button", { name: "Upload 4 documents" }));
    await screen.findByRole("heading", { name: "Your documents" });
    vi.useFakeTimers();
    await act(async () => vi.advanceTimersByTimeAsync(2000));
    vi.useRealTimers();
    const good = within(screen.getByRole("region", { name: "good.png" }));
    const failed = within(screen.getByRole("region", { name: "failed.png" }));
    const duplicate = within(screen.getByRole("region", { name: "duplicate.png" }));
    expect(good.getByRole("button", { name: "Review extracted fields" })).toBeInTheDocument();
    expect(failed.getByRole("alert")).toHaveTextContent("Model timed out.");
    expect(failed.queryByRole("button", { name: "Retry upload" })).not.toBeInTheDocument();
    expect(duplicate.getByText("Already stored")).toBeInTheDocument();
    expect(duplicate.queryByText("Processing details")).not.toBeInTheDocument();
    expect(screen.getByText("2 uploaded · 1 processed · 1 already stored · 2 failed")).toBeInTheDocument();
    await user.click(good.getByRole("button", { name: "Review extracted fields" }));
    expect(confirm).toHaveBeenCalledOnce();
    expect(onOpenDocument).not.toHaveBeenCalled();
    await user.click(good.getByText("Processing details"));
    expect(await axe(container)).toHaveNoViolations();
    await user.click(within(screen.getByRole("region", { name: "blurry.png" })).getByRole("button", { name: "Retry upload" }));
    expect(post).toBe(5);
    const calls = fetchMock.mock.calls.filter(([url]) => url === "/api/documents");
    expect(calls[4][1].body.get("file").name).toBe("blurry.png");
    for (const [, { body }] of calls) {
      expect(body.get("doc_date")).toBe("2025-11-02");
      expect(body.get("doc_type")).toBe("lab_report");
    }
    await user.click(duplicate.getByRole("button", { name: "Open document" }));
    expect(onOpenDocument).toHaveBeenCalledWith("existing");
  });

  it("removes selected files and sends only the remaining file", async () => {
    const fetchMock = vi.fn((url) => Promise.resolve(url === "/api/documents" ? uploadResponse() : jsonResponse({ state: "failed", error: "Synthetic failure" })));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<Intake patient={patient} onDone={() => {}} />);
    await selectBatch(user);
    await user.click(screen.getByRole("button", { name: "Remove one.png" }));
    await submit(user);
    expect(fetchMock.mock.calls[0][1].body.get("file").name).toBe("two.png");
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/documents")).toHaveLength(1);
  });

  it("recovers polling errors without overlapping requests or reuploading", async () => {
    vi.useFakeTimers();
    const pendingPoll = deferred();
    let reads = 0;
    const fetchMock = vi.fn((url) => {
      if (url === "/api/documents") return Promise.resolve(uploadResponse());
      if (url === "/api/documents/doc-1") return Promise.resolve(detailResponse());
      reads += 1;
      if (reads === 1) return Promise.resolve(jsonResponse({ state: "running", stage: "ocr", model: "fake-ocr", events: [] }));
      if (reads === 2) return Promise.reject(new Error("Network unavailable"));
      if (reads === 3) return pendingPoll.promise;
      return Promise.resolve(jsonResponse({ state: "done", stage: "done", events: [] }));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<Intake patient={patient} onDone={() => {}} />);
    fireEvent.change(screen.getByLabelText("Document file"), { target: { files: [new File(["image"], "labs.png", { type: "image/png" })] } });
    fireEvent.click(screen.getByLabelText(/permission to store/i));
    fireEvent.submit(screen.getByRole("button", { name: "Upload document" }).closest("form"));
    await act(async () => {});
    expect(screen.getByText("fake-ocr")).toBeInTheDocument();
    await act(async () => vi.advanceTimersByTimeAsync(2000));
    expect(screen.getByText(/Connection interrupted/)).toBeInTheDocument();
    expect(screen.getByText("fake-ocr")).toBeInTheDocument();
    await act(async () => vi.advanceTimersByTimeAsync(2000));
    await act(async () => vi.advanceTimersByTimeAsync(6000));
    expect(reads).toBe(3);
    await act(async () => pendingPoll.resolve(jsonResponse({ state: "running", stage: "saving", events: [] })));
    expect(screen.queryByText(/Connection interrupted/)).not.toBeInTheDocument();
    await act(async () => vi.advanceTimersByTimeAsync(2000));
    expect(screen.getByRole("heading", { name: "Document processed" })).toBeInTheDocument();
    await act(async () => vi.advanceTimersByTimeAsync(6000));
    expect(reads).toBe(4);
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/documents")).toHaveLength(1);
  });

  it.each([401, 403])("stops the batch on HTTP %s", async (status) => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ error: { message: "Session unavailable" } }, status));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<Intake patient={patient} onDone={() => {}} />);
    await selectBatch(user);
    await user.click(screen.getByRole("button", { name: "Upload 2 documents" }));
    expect(screen.getByText(/Sign in again before/)).toBeInTheDocument();
    expect(screen.getByText("Waiting to upload")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry upload" })).toBeDisabled();
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it.each([401, 403, 404])("does not keep polling HTTP %s", async (status) => {
    const fetchMock = vi.fn().mockResolvedValueOnce(uploadResponse()).mockResolvedValue(jsonResponse({ error: { message: "Unavailable" } }, status));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<Intake patient={patient} onDone={() => {}} />);
    await fillForm(user);
    await submit(user);
    await screen.findByText(status === 404 ? /no longer available\.$/ : /Sign in again before/);
    vi.useFakeTimers();
    await act(async () => vi.advanceTimersByTimeAsync(8000));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("requires confirmation to leave unsent files and warns on reload", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    const onDone = vi.fn();
    const user = userEvent.setup();
    render(<Intake patient={patient} onDone={onDone} />);
    await selectBatch(user);
    const reload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(reload);
    expect(reload.defaultPrevented).toBe(true);
    await user.click(screen.getByRole("button", { name: "Back to summary" }));
    expect(onDone).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Back to summary" }));
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(onDone).toHaveBeenCalledOnce();
  });

  it("stops new uploads and aborts the current request when unmounted", async () => {
    const pending = deferred();
    const fetchMock = vi.fn(() => pending.promise);
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const { unmount } = render(<Intake patient={patient} onDone={() => {}} />);
    await selectBatch(user);
    await user.click(screen.getByRole("button", { name: "Upload 2 documents" }));
    const signal = fetchMock.mock.calls[0][1].signal;
    unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => pending.resolve(uploadResponse()));
    expect(fetchMock).toHaveBeenCalledOnce();
    const reload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(reload);
    expect(reload.defaultPrevented).toBe(false);
  });

  it("ignores an old upload response when the signed-in account changes", async () => {
    const pending = deferred();
    const fetchMock = vi.fn(() => pending.promise);
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const { rerender } = render(<Intake patient={patient} onDone={() => {}} />);
    await fillForm(user);
    await submit(user);
    rerender(<Intake patient={{ id: "other", alias: "Other" }} onDone={() => {}} />);
    await act(async () => pending.resolve(uploadResponse()));
    expect(screen.getByLabelText("Document file")).toBeInTheDocument();
    expect(screen.queryByText("labs.png")).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("keeps an in-flight acceptance but stops subsequent uploads after session expiry", async () => {
    const progress = deferred();
    const second = deferred();
    let uploads = 0;
    const fetchMock = vi.fn((url) => {
      if (url.startsWith("/api/jobs/")) return progress.promise;
      uploads += 1;
      return uploads === 1 ? Promise.resolve(uploadResponse()) : second.promise;
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<Intake patient={patient} onDone={() => {}} />);
    await selectBatch(user, ["first.png", "second.png", "unsent.png"]);
    await user.click(screen.getByRole("button", { name: "Upload 3 documents" }));
    expect(uploads).toBe(2);
    await act(async () => progress.resolve(jsonResponse({ error: { message: "Expired" } }, 401)));
    await act(async () => second.resolve(uploadResponse({ document_id: "doc-2", job_id: "job-2" })));
    expect(uploads).toBe(2);
    expect(screen.getByText(/2 uploaded · 0 processed/)).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "unsent.png" })).getByText("Waiting to upload")).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([url]) => url.startsWith("/api/jobs/"))).toHaveLength(1);
  });

  it("reconciles an ambiguous failed upload with duplicate detection only on explicit retry", async () => {
    const fetchMock = vi.fn().mockRejectedValueOnce(new Error("Connection lost")).mockResolvedValueOnce(jsonResponse({ duplicate: true, document_id: "existing", status: "done" }, 409));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<Intake patient={patient} onDone={() => {}} />);
    await fillForm(user);
    await submit(user);
    expect(screen.getByRole("alert")).toHaveTextContent("Could not reach the local server");
    expect(fetchMock).toHaveBeenCalledOnce();
    await user.click(screen.getByRole("button", { name: "Retry upload" }));
    expect(await screen.findByRole("heading", { name: "Already stored" })).toHaveFocus();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("aborts pending polling and does not fetch results after unmount", async () => {
    const progress = deferred();
    const fetchMock = vi.fn().mockResolvedValueOnce(uploadResponse()).mockImplementation(() => progress.promise);
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    const { unmount } = render(<Intake patient={patient} onDone={() => {}} />);
    await fillForm(user);
    await submit(user);
    const signal = fetchMock.mock.calls[1][1].signal;
    unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => progress.resolve(jsonResponse({ state: "done" })));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
