import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import Medications from "../components/Medications";

const medications = [
  {
    id: "m-1",
    brand_raw: "Metformin",
    salt: null,
    dose: "500 mg",
    freq: "BD",
    state: "prescribed",
    source_doc_id: "d-1",
  },
  {
    id: "m-2",
    brand_raw: "Amlodipine",
    salt: null,
    dose: "5 mg",
    freq: "OD",
    state: "reported_ongoing",
    source_doc_id: "d-2",
  },
  {
    id: "m-3",
    brand_raw: "Atorvastatin",
    salt: null,
    dose: "10 mg",
    freq: "OD",
    state: "reported_stopped",
    source_doc_id: "d-3",
  },
];

describe("Medications", () => {
  it("groups medications by state without merging them", () => {
    render(<Medications medications={medications} />);

    expect(screen.getByText("Prescribed")).toBeInTheDocument();
    expect(screen.getByText("Reported ongoing")).toBeInTheDocument();
    expect(screen.getByText("Reported stopped")).toBeInTheDocument();

    expect(screen.getByText("Metformin")).toBeInTheDocument();
    expect(screen.getByText("Amlodipine")).toBeInTheDocument();
    expect(screen.getByText("Atorvastatin")).toBeInTheDocument();
  });
});
