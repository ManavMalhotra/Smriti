import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { afterEach, describe, expect, it, vi } from "vitest";
import Intake from "../pages/Intake";

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

async function fillForm(user) {
  await user.type(screen.getByLabelText("Patient alias"), "P-02");
  await user.selectOptions(screen.getByLabelText("Sex"), "F");
  await user.upload(
    screen.getByLabelText("Document file"),
    new File(["image"], "labs.png", { type: "image/png" }),
  );
  await user.selectOptions(screen.getByLabelText("Document type"), "lab_report");
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
  it("requires the patient alias, file, and consent before calling the API", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<Intake onDone={() => {}} />);

    await submit(user);
    expect(screen.getByRole("alert")).toHaveTextContent("Enter a patient alias.");

    await user.type(screen.getByLabelText("Patient alias"), "P-02");
    await submit(user);
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a document file.");

    await user.upload(
      screen.getByLabelText("Document file"),
      new File(["image"], "labs.png", { type: "image/png" }),
    );
    await submit(user);
    expect(screen.getByRole("alert")).toHaveTextContent("Confirm consent before uploading.");

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("creates a patient, uploads with local consent, and shows the queued page", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ id: "pat-1", alias: "P-02", sex: "F" }, 201))
      .mockResolvedValueOnce(
        jsonResponse(
          { document_id: "doc-1", job_id: "job-1", pages: 1, status: "queued" },
          202,
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<Intake onDone={() => {}} />);

    await fillForm(user);
    await submit(user);

    expect(await screen.findByRole("heading", { name: "Document queued" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /first page of the uploaded lab report/i })).toHaveAttribute(
      "src",
      "/api/documents/doc-1/page/1",
    );

    const [patientCall, uploadCall] = fetchMock.mock.calls;
    expect(patientCall[0]).toBe("/api/patients");
    expect(JSON.parse(patientCall[1].body)).toEqual({ alias: "P-02", sex: "F" });
    expect(uploadCall[0]).toBe("/api/documents");

    const body = uploadCall[1].body;
    expect(body).toBeInstanceOf(FormData);
    expect(body.get("patient_id")).toBe("pat-1");
    expect(body.get("doc_type")).toBe("lab_report");
    expect(body.get("consent_scope")).toBe("local");
    expect(body.get("doc_date")).toBe("2025-11-02");
    expect(body.get("file").name).toBe("labs.png");
  });

  it("keeps the created patient and allows a retry after a server rejection", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ id: "pat-1", alias: "P-02" }, 201))
      .mockResolvedValueOnce(
        jsonResponse(
          { error: { code: "rejected_quality", message: "Image is too blurry.", field: "file" } },
          422,
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse(
          { document_id: "doc-2", job_id: "job-2", pages: 1, status: "queued" },
          202,
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<Intake onDone={() => {}} />);

    await fillForm(user);
    await submit(user);

    expect(await screen.findByRole("alert")).toHaveTextContent("Image is too blurry.");
    expect(screen.queryByLabelText("Patient alias")).not.toBeInTheDocument();
    expect(screen.getByText("P-02")).toBeInTheDocument();

    await submit(user);

    expect(await screen.findByRole("heading", { name: "Document queued" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls.filter(([url]) => url === "/api/patients")).toHaveLength(1);
  });

  it("reports a duplicate without adding another document", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ id: "pat-1", alias: "P-02" }, 201))
      .mockResolvedValueOnce(
        jsonResponse({ document_id: "doc-existing", status: "queued", duplicate: true }, 409),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<Intake onDone={() => {}} />);

    await fillForm(user);
    await submit(user);

    expect(await screen.findByRole("heading", { name: "Already stored" })).toBeInTheDocument();
    expect(screen.getByText(/matches a document already on this device/i)).toBeInTheDocument();
    expect(screen.getByText("doc-existing")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("keeps the patient for another upload", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ id: "pat-1", alias: "P-02" }, 201))
      .mockResolvedValueOnce(
        jsonResponse(
          { document_id: "doc-1", job_id: "job-1", pages: 1, status: "queued" },
          202,
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<Intake onDone={() => {}} />);

    await fillForm(user);
    await submit(user);
    await screen.findByRole("heading", { name: "Document queued" });

    await user.click(screen.getByRole("button", { name: "Add another document" }));

    expect(screen.queryByLabelText("Patient alias")).not.toBeInTheDocument();
    expect(screen.getByText("P-02")).toBeInTheDocument();
    expect(screen.getByLabelText("Document file").files).toHaveLength(0);
  });

  it("has no automatically detectable accessibility violations", async () => {
    const { container } = render(<Intake onDone={() => {}} />);

    expect(await axe(container)).toHaveNoViolations();
  });
});
