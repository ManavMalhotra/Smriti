import Panel from "./Panel";
import { shortId } from "../lib/format";

export default function Problems({ problems = [] }) {
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
                <p className="item-source">Source #{shortId(problem.source_doc_id)}</p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
