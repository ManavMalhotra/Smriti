import JobProgress from "./JobProgress";

export default function Processing({ jobs = [], onQueue }) {
  if (!jobs.length) return null;
  return (
    <div className="zone-grid">
      <section className="panel" aria-labelledby="processing-head">
        <div className="result-head">
          <h2 id="processing-head">Processing</h2>
          <button type="button" className="text-button" onClick={onQueue}>
            {jobs.length === 1 ? "1 document" : `${jobs.length} documents`}
          </button>
        </div>
        <ul className="processing-list">
          {jobs.map((job) => (
            <li key={job.id}>
              <JobProgress job={job} compact />
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
