import summary from "../fixtures/summary.json";
import Header from "../components/Header";
import Problems from "../components/Problems";
import Medications from "../components/Medications";
import Results from "../components/Results";
import Pending from "../components/Pending";
import Documents from "../components/Documents";
import Footer from "../components/Footer";

export default function Dashboard({ data = summary, onAdd }) {
  return (
    <div className="shell">
      <Header patient={data.patient} coverage={data.coverage} onAdd={onAdd} />

      <main>
        <div className="zone-grid two">
          <Problems problems={data.problems} />
          <Medications medications={data.medications} />
        </div>

        <div className="zone-grid">
          <Results results={data.results} />
        </div>

        <div className="zone-grid two">
          <Pending pending={data.pending} />
          <Documents documents={data.documents} />
        </div>
      </main>

      <Footer />
    </div>
  );
}
