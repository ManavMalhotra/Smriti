import { describe, expect, it } from "vitest";
import { docTypeLabel } from "../lib/format";

describe("docTypeLabel", () => {
  it("labels imaging, pathology, and discharge types", () => {
    expect(docTypeLabel("ct")).toBe("CT report");
    expect(docTypeLabel("mri")).toBe("MRI report");
    expect(docTypeLabel("xray")).toBe("X-ray report");
    expect(docTypeLabel("pathology")).toBe("Pathology report");
    expect(docTypeLabel("radiology")).toBe("Imaging report");
    expect(docTypeLabel("discharge_summary")).toBe("Discharge summary");
  });
});
