import CoverageStrip from "./CoverageStrip";
import { formatDate, formatSex } from "../lib/format";

export default function Header({ patient, coverage, onAdd, onQueue, onDocuments, onSignOut }) {
  const gap = coverage?.gaps?.[0];
  const meta = [
    patient?.sex ? formatSex(patient.sex) : null,
    patient?.dob ? `Born ${formatDate(patient.dob)}` : null,
  ].filter(Boolean);
  const range =
    coverage?.first_date && coverage?.last_date
      ? `${formatDate(coverage.first_date)} – ${formatDate(coverage.last_date)}`
      : "No dated documents";

  return (
    <header>
      <div className="topbar">
        <div className="wordmark">Smriti</div>
        <div className="topbar-actions">
          <span className="topbar-note">Research prototype</span>
          <button type="button" className="text-button print-btn" onClick={() => window.print()}>
            Print / Export for Doctor
          </button>
          {onDocuments ? <button type="button" className="text-button" onClick={onDocuments}>Documents</button> : null}
          {onQueue ? <button type="button" className="text-button" onClick={onQueue}>Queue</button> : null}
          {onAdd ? (
            <button type="button" className="text-button" onClick={onAdd}>
              Add document
            </button>
          ) : null}
          {onSignOut ? (
            <button type="button" className="text-button" onClick={onSignOut}>
              Sign out
            </button>
          ) : null}
        </div>
      </div>

      <div className="patient">
        <div>
          <h1 tabIndex={-1}>{patient?.alias ?? "Patient"}</h1>
          {meta.length > 0 ? <p className="patient-meta">{meta.join(" · ")}</p> : null}
        </div>
        <p className="patient-range">{range}</p>
      </div>

      {gap ? (
        <div className="gap-banner">
          <strong>{gap.text}</strong>
          <span>
            {formatDate(gap.from)} – {formatDate(gap.to)}
          </span>
        </div>
      ) : null}

      <CoverageStrip coverage={coverage} />
    </header>
  );
}
