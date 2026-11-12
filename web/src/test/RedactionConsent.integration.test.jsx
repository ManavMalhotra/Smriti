import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { afterEach, describe, expect, it, vi } from "vitest";
import RedactionConsent from "../components/RedactionConsent";

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

function mockPreview() {
  const fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ pages: [{ page_num: 25, jpeg_base64: "synthetic-preview" }],
    total: 1, offset: 0, has_more: false }) });
  vi.stubGlobal("fetch", fetch);
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ clearRect: vi.fn(), fillRect: vi.fn() });
  return fetch;
}

describe("Redacted cloud consent", () => {
  it("requires preview review, accepts keyboard masks, and passes axe", async () => {
    const fetch = mockPreview();
    const user = userEvent.setup();
    const done = vi.fn();
    const { container } = render(<RedactionConsent documentId="doc-25" onResolved={done} cloudAvailable />);
    const image = await screen.findByRole("img", { name: "Source page 25 for mask review" });
    const approve = screen.getByRole("button", { name: "Approve & Send Masked Pages" });
    expect(approve).toBeDisabled();
    fireEvent.load(image);
    await user.click(screen.getByText("Add a mask with the keyboard"));
    await user.click(screen.getByRole("button", { name: "Add mask" }));
    await user.click(screen.getByRole("checkbox"));
    expect(approve).toBeEnabled();
    expect(await axe(container)).toHaveNoViolations();
    await user.click(approve);
    await waitFor(() => expect(done).toHaveBeenCalled());
    const payload = JSON.parse(fetch.mock.calls[1][1].body);
    expect(payload.approved).toBe(true);
    expect(payload.extra_redaction_boxes["25"][0].slice(0, 5)).toEqual([0, 0, 100, 100, "custom"]);
    expect(payload.extra_redaction_boxes["25"][0][5]).toEqual(expect.any(String));
  });
  it("declines cloud by keyboard without requiring loaded images", async () => {
    const fetch = mockPreview();
    render(<RedactionConsent documentId="doc-25" onResolved={() => {}} />);
    await screen.findByRole("img", { name: "Source page 25 for mask review" });
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(JSON.parse(fetch.mock.calls[1][1].body).approved).toBe(false);
  });
  it("allows erasing, editing and clearing redaction masks", async () => {
    const fetch = mockPreview();
    const user = userEvent.setup();
    render(<RedactionConsent documentId="doc-25" onResolved={() => {}} />);
    const image = await screen.findByRole("img", { name: "Source page 25 for mask review" });
    fireEvent.load(image);

    // Add mask with keyboard
    await user.click(screen.getByText("Add a mask with the keyboard"));
    await user.click(screen.getByRole("button", { name: "Add mask" }));

    // Verify mask item is rendered
    expect(screen.getByText(/Mask #1:/)).toBeInTheDocument();

    // Click Remove on the mask item
    await user.click(screen.getByRole("button", { name: "Remove", exact: true }));
    expect(screen.queryByText(/Mask #1:/)).not.toBeInTheDocument();

    // Add mask again and test edit
    await user.click(screen.getByRole("button", { name: "Add mask" }));
    expect(screen.getByText(/Mask #1:/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Edit" }));
    expect(screen.getByRole("button", { name: "Update mask" })).toBeInTheDocument();

    // Switch to Eraser tool and back
    await user.click(screen.getByRole("button", { name: "Eraser" }));
    expect(screen.getByRole("button", { name: "Eraser" })).toHaveClass("active");

    await user.click(screen.getByRole("button", { name: "Draw mask" }));
    expect(screen.getByRole("button", { name: "Draw mask" })).toHaveClass("active");

    // Clear all
    await user.click(screen.getByRole("button", { name: "Clear all masks" }));
    expect(screen.queryByText(/Mask #1:/)).not.toBeInTheDocument();
  });
});
