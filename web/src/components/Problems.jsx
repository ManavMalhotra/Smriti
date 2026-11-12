import Panel from "./Panel";
import { shortId } from "../lib/format";
import { formatDate } from "../lib/format";
import SourcePills from "./SourcePills";

export default function Problems({ problems = [], snapshot, onSource }) {
  if (snapshot && Object.values(snapshot).some((items) => items.length)) {
    return (
      <Panel title="Diagnoses & safety">
        {[["allergies", "Allergies"], ["primary_diagnoses", "Primary diagnoses"], ["major_procedures", "Surgeries & therapies"]].map(([key, title]) => (
          snapshot[key]?.length ? <section key={key} aria-label={title}>
            <h3>{title}</h3>
            <ul className={key === "major_procedures" ? "milestones" : "safety-chips"}>
              {snapshot[key].map((item) => <li key={item.id} className={key === "allergies" ? "allergy-chip" : "clinical-chip"}>
                {key === "allergies" ? <span aria-hidden="true">⚠ </span> : null}
                <strong>{item.title}</strong>{item.value_text ? ` · ${item.value_text}` : ""}
                {key === "major_procedures" ? <time dateTime={item.event_date}>{formatDate(item.event_date)}</time> : null}
                {item.status === "review" ? <span className="pill">Review</span> : null}
                <SourcePills item={item} onSource={onSource} />
              </li>)}
            </ul>
          </section> : null
        ))}
      </Panel>
    );
  }
  return (
    <Panel title="Problems">
      {problems.length === 0 ? (
        <p className="empty">No active problems recorded.</p>
      ) : (
        <ul className="list">
          {problems.map((problem) => (
            <li key={problem.id}>
              <p className="item-title">{problem.label ?? problem.condition_text ?? "Problem"}</p>
              {problem.source_doc_id ? (
                onSource ? <SourcePills item={{ ...problem, title: problem.label }} onSource={onSource} /> : <p className="item-source">Source #{shortId(problem.source_doc_id)}</p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
