import summary from "../fixtures/summary.json";
import Header from "../components/Header";
import Problems from "../components/Problems";
import Medications from "../components/Medications";
import Results from "../components/Results";
import Pending from "../components/Pending";
import Documents from "../components/Documents";

export default function Dashboard({ data = summary }) {
  return (
    <div className="shell">
      <Header patient={data.patient} coverage={data.coverage} />

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

      <footer className="footer">
        <p>Research prototype. Not a medical device. Not for clinical use.</p>
        <p>Data stays on this device.</p>
      </footer>
    </div>
  );
}
