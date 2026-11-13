import Header from "../components/Header";
import Problems from "../components/Problems";
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
  onRetry,
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
  const summary = view.standardized_summary;
  const hasSummary = Boolean(
    summary?.concise_history_summary ||
      summary?.chronic_conditions?.length ||
      view.problems?.length ||
      Object.values(view.clinical_snapshot ?? {}).some((items) => items?.length),
  );
  const hasRecords = Boolean(
    view.results?.length ||
      view.medications?.length ||
      view.pending?.length ||
      view.documents?.length ||
      timeline.length,
  );

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
            <p>{error}</p>
            {onRetry ? (
              <button type="button" className="text-button" onClick={onRetry}>
                Try again
              </button>
            ) : null}
          </div>
        ) : null}

        {ready ? (
          <>
            <Processing jobs={activeJobs} onQueue={onQueue} />

            {hasSummary ? (
              <div className="safety-bar">
                <Problems
                  problems={view.problems}
                  snapshot={view.clinical_snapshot}
                  narrative={summary?.concise_history_summary}
                  conditions={summary?.chronic_conditions}
                  onSource={setSource}
                />
              </div>
            ) : null}

            {!hasRecords ? (
              <section className="panel empty-state" aria-labelledby="empty-heading">
                <h2 id="empty-heading">Start with a document</h2>
                <p>
                  Upload a prescription, lab report, or discharge summary. Smriti reads it on
                  this device and links every value back to its page.
                </p>
                <button type="button" className="button-primary" onClick={onAdd}>
                  Add document
                </button>
              </section>
            ) : (
              <>
                <div className="clinical-grid">
                  <div className="clinical-history">
                    <History
                      reports={timeline}
                      documents={view.documents}
                      loading={timelineLoading}
                      error={timelineError}
                      onOpen={onOpenDocument}
                      onSource={setSource}
                    />
                  </div>
                  <div className="clinical-meds">
                    <Medications
                      medications={view.medications}
                      timeline={view.medications_timeline}
                      onSource={setSource}
                      onOpenDocument={onOpenDocument}
                    />
                  </div>
                  <div className="clinical-results">
                    <Results
                      results={view.results}
                      organGroups={view.organ_groups}
                      onSource={setSource}
                    />
                  </div>
                  <div className="clinical-pending">
                    <Pending pending={view.pending} />
                  </div>
                </div>

                <div className="zone-grid">
                  <UnassignedFindings
                    results={view.results}
                    timeline={timeline}
                    onOpenDocument={onOpenDocument}
                  />
                </div>
              </>
            )}
          </>
        ) : null}
      </main>

      <Footer />
      <SourceOverlay source={source} onClose={() => setSource(null)} drawer />
    </div>
  );
}
