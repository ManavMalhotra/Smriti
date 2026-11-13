export default function Topbar({
  current,
  back,
  onDocuments,
  onQueue,
  onAdd,
  onSignOut,
}) {
  return (
    <div className="topbar">
      <a className="wordmark" href="#/summary" aria-label="Smriti home">
        Smriti
      </a>
      <nav className="topbar-actions" aria-label="Primary">
        {back ? (
          <button type="button" className="text-button" onClick={back.onClick}>
            {back.label}
          </button>
        ) : null}
        <button type="button" className="text-button print-btn" onClick={() => window.print()}>
          Print / Export for Doctor
        </button>
        {onDocuments ? (
          <button
            type="button"
            className="text-button"
            aria-current={current === "documents" ? "page" : undefined}
            onClick={onDocuments}
          >
            Documents
          </button>
        ) : null}
        {onQueue ? (
          <button
            type="button"
            className="text-button"
            aria-current={current === "queue" ? "page" : undefined}
            onClick={onQueue}
          >
            Queue
          </button>
        ) : null}
        {onAdd ? (
          <button type="button" className="button-primary" onClick={onAdd}>
            Add document
          </button>
        ) : null}
        {onSignOut ? (
          <button type="button" className="text-button" onClick={onSignOut}>
            Sign out
          </button>
        ) : null}
      </nav>
    </div>
  );
}
