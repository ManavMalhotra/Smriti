import Header from "../components/Header";
import Problems from "../components/Problems";
import Medications from "../components/Medications";
import Results from "../components/Results";
import Pending from "../components/Pending";
import Documents from "../components/Documents";
import Processing from "../components/Processing";
import Timeline from "../components/Timeline";
import UnassignedFindings from "../components/UnassignedFindings";
import Footer from "../components/Footer";

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
  onOpenDocument,
  onSignOut,
  loading = false,
  error = "",
  timeline = [],
  timelineLoading = false,
  timelineError = "",
  activeJobs = [],
}) {
  const view = data ?? {
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
    <div className="shell">
      <Header
        patient={view.patient}
        coverage={view.coverage}
        onAdd={onAdd}
        onQueue={onQueue}
        onSignOut={onSignOut}
      />

      <main>
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

            <div className="zone-grid">
              <Timeline
                reports={timeline}
                loading={timelineLoading}
                error={timelineError}
                onOpen={onOpenDocument}
              />
            </div>

            <div className="zone-grid two">
              <Problems problems={view.problems} />
              <Medications medications={view.medications} />
            </div>

            <div className="zone-grid">
              <Results results={view.results} />
            </div>

            <div className="zone-grid two">
              <Pending pending={view.pending} />
              <Documents documents={view.documents} onOpen={onOpenDocument} />
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
    </div>
  );
}
