export default function Value({ value, unit, flag }) {
  const missing = value == null || value === "—";

  return (
    <span className="value">
      <span className="num">{missing ? "—" : value}</span>
      {unit && !missing ? <span className="unit"> {unit}</span> : null}
      {flag ? <span className="flag">{flag}</span> : null}
    </span>
  );
}
