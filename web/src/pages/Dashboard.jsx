import Header from "../components/Header";
import Problems from "../components/Problems";
import StandardizedSummary from "../components/StandardizedSummary";
import Medications from "../components/Medications";
import Results from "../components/Results";
import Pending from "../components/Pending";
import Processing from "../components/Processing";
import History from "../components/History";
import UnassignedFindings from "../components/UnassignedFindings";
import Footer from "../components/Footer";
import SourceOverlay from "../components/SourceOverlay";
import { useState } from "react";

const EMPTY_COVERAGE = {
  first_date: null,
  last_date: null,
  quarters: [],
  gaps: [],
};

export default function Dashboard({
  data,
  patient,
  onAdd,
  onQueue,
  onDocuments,
  onOpenDocument,
  onSignOut,
  loading = false,
  error = "",
  timeline = [],
  timelineLoading = false,
  timelineError = "",
  activeJobs = [],
  onSummaryUpdate,
}) {
  const [source, setSource] = useState(null);
  const [localSummary, setLocalSummary] = useState(null);
  const view = localSummary ?? data ?? {
    patient,
    coverage: EMPTY_COVERAGE,
    problems: [],
    medications: [],
    results: [],
    pending: [],
    documents: [],
  };
  const ready = Boolean(data) || (!loading && !error);

  return (
    <div className="shell clinical-dashboard">
      <Header
        patient={view.patient}
        coverage={view.coverage}
        onAdd={onAdd}
        onQueue={onQueue}
        onDocuments={onDocuments}
        onSignOut={onSignOut}
      />

      <main>
        <div className="doctor-print-header" aria-hidden="true">
          <h1>Smriti · Clinical Summary Report</h1>
          <p>Patient: {view.patient?.alias} {view.patient?.uhid ? `· UHID: ${view.patient.uhid}` : ""} · Generated on {new Date().toLocaleDateString("en-GB", { dateStyle: "long" })}</p>
        </div>
        {loading && !data ? (
          <p className="empty" role="status">
            Loading summary…
          </p>
        ) : null}
        {error ? (
          <div className="alert" role="alert">
            {error}
          </div>
        ) : null}

        {ready ? (
          <>
            <Processing jobs={activeJobs} onQueue={onQueue} />

            {view.standardized_summary ? (
              <StandardizedSummary
                summary={view.standardized_summary}
                onOpenDocument={onOpenDocument}
              />
            ) : (view.problems?.length || Object.values(view.clinical_snapshot ?? {}).some((items) => items.length)) ? (
              <div className="safety-bar"><Problems problems={view.problems} snapshot={view.clinical_snapshot} onSource={setSource} /></div>
            ) : null}
            <div className="clinical-grid">
              <div className="clinical-history">
                <History
                  reports={timeline?.length ? timeline : (view.reports || view.master_timeline || [])}
                  documents={view.documents}
                  events={view.master_timeline}
                  loading={timelineLoading}
                  error={timelineError}
                  onOpen={onOpenDocument}
                  onSource={setSource}
                />
              </div>
              <div className="clinical-meds"><Medications medications={view.medications} timeline={view.medications_timeline} onSource={setSource} onOpenDocument={onOpenDocument} /></div>
              <div className="clinical-results"><Results results={view.results} organGroups={view.organ_groups} onSource={setSource} /></div>
              <div className="clinical-pending"><Pending pending={view.pending} /></div>
            </div>

            <div className="zone-grid">
              <UnassignedFindings
                results={view.results}
                timeline={timeline}
                onOpenDocument={onOpenDocument}
              />
            </div>
          </>
        ) : null}
      </main>

      <Footer />
      <SourceOverlay source={source} onClose={() => setSource(null)} drawer />
    </div>
  );
}
