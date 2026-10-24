import { fireEvent, render, screen } from "@testing-library/react";
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

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Intake", () => {
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
    expect(screen.getByText("P-02")).toBeInTheDocument();
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

  it("polls a finished job and renders extracted fields and text", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(uploadResponse())
      .mockResolvedValueOnce(
        jsonResponse({ id: "job-1", state: "done", page: 1, total: 1, error: null }),
      )
      .mockResolvedValueOnce(detailResponse());
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<Intake patient={patient} onDone={() => {}} />);

    await fillForm(user, { type: "lab_report" });
    await submit(user);

    expect(await screen.findByRole("heading", { name: "Document processed" })).toHaveFocus();
    expect(screen.getByText("Lab report")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: /extracted fields/i })).toBeInTheDocument();
    expect(screen.getByText("HbA1c")).toBeInTheDocument();
    expect(screen.getByText("8.9")).toBeInTheDocument();
    expect(screen.getByText("4–6")).toBeInTheDocument();
    expect(screen.getByText("Extracted text")).toBeInTheDocument();
    expect(screen.getByText("HbA1c 8.9 %")).toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
      "/api/documents",
      "/api/jobs/job-1",
      "/api/documents/doc-1",
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
    expect(screen.getByLabelText("Document file").files).toHaveLength(1);

    await submit(user);

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
    expect(screen.getByText("P-02")).toBeInTheDocument();
    expect(screen.getByLabelText("Document file").files).toHaveLength(0);
    expect(screen.getByLabelText("Document file")).toHaveFocus();
  });

  it("has no automatically detectable accessibility violations", async () => {
    const { container } = render(<Intake patient={patient} onDone={() => {}} />);

    expect(await axe(container)).toHaveNoViolations();
  });
});
