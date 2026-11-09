import Header from "../components/Header";
import Problems from "../components/Problems";
import Medications from "../components/Medications";
import Results from "../components/Results";
import Pending from "../components/Pending";
import Processing from "../components/Processing";
import History from "../components/History";
import UnassignedFindings from "../components/UnassignedFindings";
import Footer from "../components/Footer";

// Problems has no extractor yet (summary.py returns []); keep it off-screen until it produces data.
const SHOW_PROBLEMS = false;

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
              <History
                reports={timeline}
                documents={view.documents}
                loading={timelineLoading}
                error={timelineError}
                onOpen={onOpenDocument}
              />
            </div>

            <div className={SHOW_PROBLEMS ? "zone-grid two" : "zone-grid"}>
              {SHOW_PROBLEMS ? <Problems problems={view.problems} /> : null}
              <Medications medications={view.medications} />
            </div>

            <div className="zone-grid">
              <Results results={view.results} />
            </div>

            <div className="zone-grid">
              <Pending pending={view.pending} />
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
