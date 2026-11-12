import { useState } from "react";
import Panel from "./Panel";
import SourcePills from "./SourcePills";

const STATES = [
  ["prescribed", "Prescribed"],
  ["reported_ongoing", "Reported ongoing"],
  ["reported_stopped", "Reported stopped"],
];
const ACTIVE_LIMIT = 5;

function MedicationRow({ med, onSource, onOpenDocument }) {
  return <li>
    <p className="item-title">{med.brand_raw}{med.salt ? ` (${med.salt})` : ""}</p>
    <p className="item-meta">{[med.dose, med.freq].filter(Boolean).join(" · ") || "Dose not recorded"}</p>
    {med.engine === "gemini-3.8-flash-high" ? <span className="pill">{med.confidence_note === "deciphered_handwriting" ? "AI handwriting · review" : "AI extraction · review"}</span> : null}
    {(med.source_doc_id || med.doc_id) ? <button type="button" className="text-button item-source"
      onClick={() => onOpenDocument?.(med.source_doc_id || med.doc_id, med.page_num || med.page || 1)}>
      Prescription · page {med.page_num || med.page || 1}
    </button> : null}
    <SourcePills item={med} onSource={onSource} />
  </li>;
}

export default function Medications({ medications = [], timeline, onSource, onOpenDocument }) {
  const [expanded, setExpanded] = useState(false);
  if (timeline && Object.values(timeline).some((items) => items.length)) {
    const active = timeline.active_scheduled ?? [];
    const rest = [
      ["conditional_sos_or", "As-needed prescriptions"],
      ["historical_completed", "Earlier prescriptions"],
    ].filter(([key]) => timeline[key]?.length);
    return <Panel title="Medications on record">
      <p className="result-note">A prescription does not confirm current use.</p>
      {active.length ? <section className="state-group" aria-label="Daily prescriptions">
        <h3>Daily prescriptions <span className="count-badge">{active.length}</span></h3>
        <ul className="list">{(expanded ? active : active.slice(0, ACTIVE_LIMIT)).map((med) =>
          <MedicationRow key={med.id} med={med} onSource={onSource} onOpenDocument={onOpenDocument} />)}</ul>
        {active.length > ACTIVE_LIMIT ? <button type="button" className="text-button" aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}>{expanded ? "Show fewer" : `Show all ${active.length}`}</button> : null}
      </section> : null}
      {rest.map(([key, title]) => <details className="state-group compact-med-group" key={key}>
        <summary>{title} <span className="count-badge">{timeline[key].length}</span></summary>
        <ul className="list">{timeline[key].map((med) => <MedicationRow key={med.id} med={med}
          onSource={onSource} onOpenDocument={onOpenDocument} />)}</ul>
      </details>)}
    </Panel>;
  }

  const groups = STATES.map(([state, label]) => [label, medications.filter((item) => item.state === state)])
    .filter(([, items]) => items.length);
  return <Panel title="Medications on record">
    {!medications.length ? <p className="empty">No medications recorded.</p> : groups.map(([label, items]) => (
      <details className="state-group compact-med-group" key={label}>
        <summary>{label} <span className="count-badge">{items.length}</span></summary>
        <ul className="list">{items.map((med) => <li key={med.id}>
          <p className="item-title">{med.brand_raw}{med.salt ? ` (${med.salt})` : ""}</p>
          <p className="item-meta">{[med.dose, med.freq].filter(Boolean).join(" · ") || "Dose not recorded"}</p>
          {med.source_doc_id ? <button type="button" className="text-button item-source"
            onClick={() => onOpenDocument?.(med.source_doc_id, med.page_num || 1)}>Prescription · page {med.page_num || 1}</button> : null}
        </li>)}</ul>
      </details>
    ))}
  </Panel>;
}
