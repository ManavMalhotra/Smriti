import Panel from "./Panel";
import { shortId } from "../lib/format";

const STATES = [
  ["prescribed", "Prescribed"],
  ["reported_ongoing", "Reported ongoing"],
  ["reported_stopped", "Reported stopped"],
];

export default function Medications({ medications = [] }) {
  const groups = STATES.map(([state, label]) => [
    label,
    medications.filter((medication) => medication.state === state),
  ]).filter(([, items]) => items.length > 0);

  return (
    <Panel title="Current medications">
      {medications.length === 0 ? (
        <p className="empty">No medications recorded.</p>
      ) : (
        groups.map(([label, items]) => (
          <section
            className="state-group"
            key={label}
            aria-labelledby={`state-${label.toLowerCase().replace(/\s+/g, "-")}`}
          >
            <h3
              className="state-heading"
              id={`state-${label.toLowerCase().replace(/\s+/g, "-")}`}
            >
              {label}
            </h3>
            <ul className="list">
              {items.map((medication) => (
                <li key={medication.id}>
                  <p className="item-title">
                    {medication.brand_raw}
                    {medication.salt ? ` (${medication.salt})` : ""}
                  </p>
                  <p className="item-meta">
                    {[medication.dose, medication.freq].filter(Boolean).join(" · ") ||
                      "Dose not recorded"}
                  </p>
                  {medication.source_doc_id ? (
                    <p className="item-source">Source #{shortId(medication.source_doc_id)}</p>
                  ) : null}
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
    </Panel>
  );
}
