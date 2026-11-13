import CoverageStrip from "./CoverageStrip";
import Topbar from "./Topbar";
import { formatDate, formatSex } from "../lib/format";

export default function Header({
  patient,
  coverage,
  documents = [],
  onAdd,
  onQueue,
  onDocuments,
  onOpenDocument,
  onSignOut,
}) {
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
      <Topbar
        current="summary"
        onDocuments={onDocuments}
        onQueue={onQueue}
        onAdd={onAdd}
        onSignOut={onSignOut}
      />

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

      <CoverageStrip
        coverage={coverage}
        documents={documents}
        onOpenDocument={onOpenDocument}
      />
    </header>
  );
}
