import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }) => <div>{children}</div>,
  LineChart: ({ children }) => <div>{children}</div>,
  ReferenceArea: ({ y1, y2, strokeDasharray }) => <div data-testid="normal-band" data-low={y1} data-high={y2} data-dashes={strokeDasharray} />,
  ReferenceLine: () => null, Line: () => null, XAxis: () => null, YAxis: () => null, Tooltip: () => null,
}));
import TrendChart, { ClinicalDot } from "../components/TrendChart";

describe("Clinical reference bands", () => {
  it("plots the source reference range with dashed bounds", () => {
    render(<TrendChart result={{ display: "Hemoglobin", ref_low: 12, ref_high: 16,
      points: [{ date: "2026-04-08", value: 9.1 }, { date: "2026-05-08", value: 12.1 }] }} />);
    expect(screen.getByTestId("normal-band")).toHaveAttribute("data-low", "12");
    expect(screen.getByTestId("normal-band")).toHaveAttribute("data-high", "16");
    expect(screen.getByTestId("normal-band")).toHaveAttribute("data-dashes", "4 4");
  });
  it("uses circles and triangles, not color alone", () => {
    const result = { ref_low: 12, ref_high: 16 };
    const { container } = render(<svg><ClinicalDot cx={10} cy={10} payload={{ value: 13 }} result={result} />
      <ClinicalDot cx={30} cy={10} payload={{ value: 9, abnormal_flag: "low" }} result={result} /></svg>);
    expect(container.querySelector("circle")).toHaveAttribute("fill", "#17683f");
    expect(container.querySelector("path")).toHaveAttribute("fill", "#865400");
  });
});
