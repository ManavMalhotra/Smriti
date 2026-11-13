import Panel from "./Panel";
import SourcePills from "./SourcePills";
import { formatDate, shortId } from "../lib/format";

const SAFETY = [
  ["allergies", "Allergies"],
  ["primary_diagnoses", "Diagnoses"],
  ["major_procedures", "Surgeries and therapies"],
];

export default function Problems({
  problems = [],
  snapshot,
  narrative,
  conditions = [],
  onSource,
}) {
  const hasSnapshot = Boolean(
    snapshot && Object.values(snapshot).some((items) => items?.length),
  );
  const hasContent = Boolean(
    narrative || conditions.length || hasSnapshot || problems.length,
  );

  return (
    <Panel title="Clinical summary">
      {!hasContent ? <p className="empty">No clinical summary yet.</p> : null}
      {narrative ? <p className="clinical-narrative">{narrative}</p> : null}
      {conditions.length ? (
        <ul className="condition-chips" aria-label="Long-term conditions">
          {conditions.map((condition) => {
            const label = condition.name ?? condition.title;
            return label ? <li key={label}>{label}</li> : null;
          })}
        </ul>
      ) : null}

      {hasSnapshot ? (
        <div className="safety-grid">
          {SAFETY.map(([key, title]) =>
            snapshot[key]?.length ? (
              <section className="safety-section" key={key} aria-label={title}>
                <h3>{title}</h3>
                <ul className={key === "major_procedures" ? "milestones" : "safety-chips"}>
                  {snapshot[key].map((item) => (
                    <li
                      key={item.id}
                      className={key === "allergies" ? "allergy-chip" : "clinical-chip"}
                    >
                      <strong>{item.title}</strong>
                      {item.value_text ? ` · ${item.value_text}` : ""}
                      {key === "major_procedures" && item.event_date ? (
                        <time dateTime={item.event_date}>{formatDate(item.event_date)}</time>
                      ) : null}
                      {key === "major_procedures" && item.is_backdated_from_summary && item.report_date ? (
                        <span className="doc-review">
                          Recorded in Discharge Summary ({formatDate(item.report_date)})
                        </span>
                      ) : null}
                      {item.status === "review" ? <span className="pill">Needs review</span> : null}
                      <SourcePills item={item} onSource={onSource} />
                    </li>
                  ))}
                </ul>
              </section>
            ) : null,
          )}
        </div>
      ) : problems.length ? (
          <ul className="list">
            {problems.map((problem) => (
              <li key={problem.id}>
                <p className="item-title">{problem.label ?? problem.condition_text ?? "Problem"}</p>
                {problem.source_doc_id ? (
                  onSource ? (
                    <SourcePills
                      item={{ ...problem, title: problem.label }}
                      onSource={onSource}
                    />
                  ) : (
                    <p className="item-source">Source #{shortId(problem.source_doc_id)}</p>
                  )
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}
    </Panel>
  );
}
