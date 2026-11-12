import {
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatDate, formatRange } from "../lib/format";

function CustomTooltip({ active, payload, label, unit, refLow, refHigh }) {
  if (!active || !payload || !payload.length) return null;
  const value = payload[0].value;
  const point = payload[0].payload ?? {};
  if (Object.hasOwn(point, "ref_min")) refLow = point.ref_min;
  if (Object.hasOwn(point, "ref_max")) refHigh = point.ref_max;
  let status = null;
  if (refHigh != null && value > refHigh) status = "High";
  else if (refLow != null && value < refLow) status = "Low";
  else if (refLow != null || refHigh != null) status = "In range";

  return (
    <div className="trend-tooltip">
      <p className="trend-tooltip-date">{formatDate(label)}</p>
      <p className="trend-tooltip-value">
        <strong>{value}</strong>
        {unit ? ` ${unit}` : ""}
        {status ? (
          <span className={`trend-badge trend-badge-${status.toLowerCase().replace(" ", "-")}`}>
            {status}
          </span>
        ) : null}
      </p>
      {refLow != null || refHigh != null ? (
        <p className="trend-tooltip-baseline">
          Expected baseline: {formatRange(refLow, refHigh)} {unit || ""}
        </p>
      ) : null}
    </div>
  );
}

export function ClinicalDot({ cx, cy, payload, onSource, result }) {
  if (cx == null || cy == null) return null;
  const low = Object.hasOwn(payload, "ref_min") ? payload.ref_min : result.ref_low;
  const high = Object.hasOwn(payload, "ref_max") ? payload.ref_max : result.ref_high;
  const abnormal = ["high", "low", "critical", "positive_finding"].includes(payload.abnormal_flag) ||
    (low != null && payload.value < low) || (high != null && payload.value > high);
  const open = () => onSource?.({ ...payload, analyte: result.display,
    pageUrl: `/api/documents/${payload.document_id}/page/${payload.page}` });
  if (abnormal) return <path d={`M ${cx} ${cy - 6} L ${cx - 6} ${cy + 5} L ${cx + 6} ${cy + 5} Z`}
    fill={payload.abnormal_flag === "critical" ? "#b42318" : "#865400"} stroke="white" onClick={open} />;
  return <circle cx={cx} cy={cy} r={4} fill={low != null && high != null ? "#17683f" : "#5f5f64"}
    stroke="white" onClick={open} />;
}

export default function TrendChart({ result, onSource }) {
  const data = result.points.map((point) => ({
    ...point,
    date: point.date,
    value: point.value,
  }));

  // shortcut: conflicting intervals stay per-reading in the table; add time-varying bands if needed.
  const varies = result.points.some((point) =>
    (Object.hasOwn(point, "ref_min") && point.ref_min !== result.ref_low) || (Object.hasOwn(point, "ref_max") && point.ref_max !== result.ref_high));
  const hasTwoSidedRef = !varies && result.ref_low != null && result.ref_high != null;
  const hasOnlyHigh = !varies && result.ref_low == null && result.ref_high != null;
  const hasOnlyLow = !varies && result.ref_low != null && result.ref_high == null;

  return (
    <div className="trend" aria-hidden="true">
      <ResponsiveContainer width="100%" height={190}>
        <LineChart data={data} margin={{ top: 12, right: 12, bottom: 4, left: 4 }}>
          {hasTwoSidedRef ? (
            <ReferenceArea
              y1={result.ref_low}
              y2={result.ref_high}
              fill="rgba(16, 185, 129, 0.08)"
              stroke="rgba(16, 185, 129, 0.25)"
              strokeDasharray="4 4"
              ifOverflow="extendDomain"
            />
          ) : null}
          {hasTwoSidedRef ? <>
            <ReferenceLine y={result.ref_low} stroke="#17683f" strokeDasharray="4 4" ifOverflow="extendDomain" />
            <ReferenceLine y={result.ref_high} stroke="#17683f" strokeDasharray="4 4" ifOverflow="extendDomain" />
          </> : null}

          {hasOnlyHigh ? (
            <ReferenceLine
              y={result.ref_high}
              stroke="#059669"
              strokeDasharray="3 3"
              label={{
                value: `Expected ≤ ${result.ref_high}`,
                position: "insideTopRight",
                fill: "#059669",
                fontSize: 10,
              }}
            />
          ) : null}

          {hasOnlyLow ? (
            <ReferenceLine
              y={result.ref_low}
              stroke="#059669"
              strokeDasharray="3 3"
              label={{
                value: `Expected ≥ ${result.ref_low}`,
                position: "insideBottomRight",
                fill: "#059669",
                fontSize: 10,
              }}
            />
          ) : null}

          <XAxis
            dataKey="date"
            tickFormatter={formatDate}
            tick={{ fontSize: 11, fill: "#6e6e73" }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            domain={["auto", "auto"]}
            tick={{ fontSize: 11, fill: "#6e6e73" }}
            axisLine={false}
            tickLine={false}
            width={40}
          />
          <Tooltip
            content={
              <CustomTooltip
                unit={result.unit}
                refLow={result.ref_low}
                refHigh={result.ref_high}
              />
            }
          />
          <Line
            type="linear"
            dataKey="value"
            stroke="#1d1d1f"
            strokeWidth={1.8}
            dot={<ClinicalDot onSource={onSource} result={result} />}
            activeDot={{ r: 5, fill: "#0066cc" }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
