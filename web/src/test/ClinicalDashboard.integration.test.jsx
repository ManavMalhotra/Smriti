import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "jest-axe";
import { describe, expect, it } from "vitest";
import Dashboard from "../pages/Dashboard";
import Problems from "../components/Problems";
import summary from "../fixtures/summary.json";

const event = { id: "surgery", category: "procedure_surgery", title: "Right Mastectomy + ALND", value_text: "Completed",
  event_date: "2025-09-09", report_date: "2026-04-08", doc_id: "doc-31", page_num: 31,
  bbox_2d: [100, 200, 300, 800], status: "review", engine: "gemini-3.8-flash-high", is_backdated_from_summary: true };
const snapshot = { primary_diagnoses: [{ ...event, id: "dx", title: "Carcinoma right breast", value_text: "pT2(m)pN3a · ER+/PR+/HER2-" }],
  allergies: [{ ...event, id: "allergy", title: "Allergy: Sulpha drugs", value_text: "Reported" }], major_procedures: [event] };

describe("Unified clinical dashboard", () => {
  it("shows safety, conditional medicines and backdated history with accessible source boxes", async () => {
    const user = userEvent.setup();
    const { container } = render(<Dashboard data={{ ...summary, clinical_snapshot: snapshot, master_timeline: [event],
      organ_groups: { sugar_metabolism: [{ analyte_id: "hba1c", unit: "%", series: [] }] },
      medications_timeline: { active_scheduled: [], historical_completed: [], conditional_sos_or: [{ ...event,
        id: "med", brand_raw: "Valcivir OR Acyclovir", dose: "1g OR 800mg", freq: "SOS" }] } }} />);
    expect(screen.getByRole("heading", { name: "Allergies" })).toBeInTheDocument();
    expect(screen.getByText(/As-needed prescriptions/)).toBeInTheDocument();
    expect(screen.getByText(/Recorded in Discharge Summary/)).toHaveTextContent("8 Apr 2026");
    expect(screen.queryByRole("button", { name: "Patient Friendly" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Doctor Clinical" })).not.toBeInTheDocument();
    expect(await axe(container)).toHaveNoViolations();
    const source = screen.getByRole("button", { name: "Open source for Allergy: Sulpha drugs on page 31" });
    source.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("img", { name: "Source page 31" }).querySelector("img")).toHaveAttribute("src", "/api/documents/doc-31/page/31");
    // PageOverlay uses normalized xyxy; the source helper must swap y/x exactly once.
    const overlay = container.querySelector('[style*="left: 20%"]');
    expect(overlay).toBeInTheDocument();
    expect(await axe(container)).toHaveNoViolations();
    await user.keyboard("{Escape}");
    expect(source).toHaveFocus();
  });

  it("Problems is independently accessible", async () => {
    const { container } = render(<main><Problems snapshot={snapshot} onSource={() => {}} /></main>);
    expect(await axe(container)).toHaveNoViolations();
  });

  it("keeps safety data visible beside a standardized summary", () => {
    render(
      <Dashboard
        data={{
          ...summary,
          clinical_snapshot: snapshot,
          standardized_summary: {
            concise_history_summary: "Known sulfa allergy.",
            chronic_conditions: [{ name: "Type 2 diabetes", status: "active" }],
            year_wise_history: [{ title: "Duplicate report row", exact_date: "2025-11-02" }],
          },
        }}
      />,
    );
    expect(screen.getByRole("heading", { name: "Clinical summary" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Allergies" })).toBeInTheDocument();
    expect(screen.getByText("Known sulfa allergy.")).toBeInTheDocument();
    expect(screen.getByText("Type 2 diabetes")).toBeInTheDocument();
    expect(screen.queryByText("Duplicate report row")).not.toBeInTheDocument();
  });
});
