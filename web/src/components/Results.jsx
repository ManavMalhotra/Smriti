import { lazy, Suspense, useState } from "react";
import Panel from "./Panel";
import SourceOverlay from "./SourceOverlay";
import Value from "./Value";
import { formatDate, formatRange } from "../lib/format";

// Recharts only loads when a result actually has a trend to draw.
const TrendChart = lazy(() => import("./TrendChart"));

export default function Results({ results = [] }) {
  const [source, setSource] = useState(null);

  return (
    <Panel title="Results">
      {results.length === 0 ? (
        <p className="empty">No results recorded.</p>
      ) : (
        results.map((result) => (
          <section
            className="result"
            key={result.analyte_id}
            aria-labelledby={`result-${result.analyte_id}`}
          >
            <div className="result-head">
              <div>
                <h3 id={`result-${result.analyte_id}`}>{result.display}</h3>
                <p className="result-ref">
                  Reference{" "}
                  <Value
                    value={formatRange(result.ref_low, result.ref_high)}
                    unit={result.unit}
                  />
                </p>
              </div>
              <p className="result-count">
                {result.points.length} {result.points.length === 1 ? "reading" : "readings"}
              </p>
            </div>

            {result.points.length > 1 ? (
              <Suspense fallback={null}>
                <TrendChart result={result} />
              </Suspense>
            ) : null}

            <div className="table-wrap">
              <table
                aria-describedby={
                  result.points.some((point) => point.flag_printed)
                    ? `result-${result.analyte_id}-flag-note`
                    : undefined
                }
              >
                <caption className="sr-only">{result.display} readings</caption>
                <thead>
                  <tr>
                    <th scope="col">Date</th>
                    <th scope="col">Value</th>
                    <th scope="col">Source</th>
                  </tr>
                </thead>
                <tbody>
                  {result.points.map((point) => (
                    <tr key={point.observation_id}>
                      <td>{formatDate(point.date)}</td>
                      <td>
                        <Value
                          value={point.value}
                          unit={result.unit}
                          flag={point.flag_printed}
                        />
                      </td>
                      <td>
                        <button
                          type="button"
                          className="text-button"
                          onClick={() =>
                            setSource({
                              ...point,
                              analyte: result.display,
                              pageUrl: null,
                            })
                          }
                          aria-label={`Open source for ${result.display} on ${formatDate(
                            point.date,
                          )}`}
                        >
                          Source
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {result.points.some((point) => point.flag_printed) ? (
              <p
                className="result-note"
                id={`result-${result.analyte_id}-flag-note`}
              >
                Flags are shown exactly as printed on the source document.
              </p>
            ) : null}

            {result.excluded?.length > 0 ? (
              <div className="excluded" role="note">
                <h4>Excluded from results</h4>
                <ul>
                  {result.excluded.map((item, index) => (
                    <li key={`${item.document_id}-${index}`}>
                      {item.reason}
                      <span className="item-source"> Source {item.document_id}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </section>
        ))
      )}

      <SourceOverlay source={source} onClose={() => setSource(null)} />
    </Panel>
  );
}
