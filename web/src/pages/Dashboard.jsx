import Header from "../components/Header";
import Problems from "../components/Problems";
import Medications from "../components/Medications";
import Results from "../components/Results";
import Pending from "../components/Pending";
import Documents from "../components/Documents";
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
  onOpenDocument,
  onSignOut,
  loading = false,
  error = "",
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

  return (
    <div className="shell">
      <Header
        patient={view.patient}
        coverage={view.coverage}
        onAdd={onAdd}
        onSignOut={onSignOut}
      />

      <main>
        {loading ? (
          <p className="empty" role="status">
            Loading summary…
          </p>
        ) : null}
        {error ? (
          <div className="alert" role="alert">
            {error}
          </div>
        ) : null}

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
      </main>

      <Footer />
    </div>
  );
}
