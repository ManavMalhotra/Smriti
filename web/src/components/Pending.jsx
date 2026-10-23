import Panel from "./Panel";
import { actionLabel, anchorLabel, formatDate, stateLabel } from "../lib/format";

export default function Pending({ pending = [] }) {
  return (
    <Panel title="Pending">
      {pending.length === 0 ? (
        <p className="empty">Nothing pending.</p>
      ) : (
        <ul className="list">
          {pending.map((item) => {
            const meta = [
              actionLabel(item.action_type),
              item.due_date ? `Due ${formatDate(item.due_date)}` : null,
              item.anchor_event ? `Anchored to ${anchorLabel(item.anchor_event)}` : null,
            ].filter(Boolean);

            return (
              <li key={item.id}>
                <p className="pending-text">{item.text}</p>
                {meta.length > 0 ? <p className="pending-meta">{meta.join(" · ")}</p> : null}
                {item.state ? (
                  <p className="pending-state">
                    <span className="pill">{stateLabel(item.state)}</span>
                  </p>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
