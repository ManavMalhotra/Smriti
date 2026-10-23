import {
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";
import { formatDate } from "../lib/format";

export default function TrendChart({ result }) {
  const data = result.points.map((point) => ({
    date: point.date,
    value: point.value,
  }));
  const hasReference = result.ref_low != null && result.ref_high != null;

  return (
    <div className="trend" aria-hidden="true">
      <ResponsiveContainer width="100%" height={180}>
        <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          {hasReference ? (
            <ReferenceArea
              y1={result.ref_low}
              y2={result.ref_high}
              fill="#f0f0f2"
              stroke="none"
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
            width={38}
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke="#1d1d1f"
            strokeWidth={1.5}
            dot={{ r: 3, fill: "#1d1d1f" }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
