import { lazy, Suspense, useState } from "react";
import Panel from "./Panel";
import SourceOverlay from "./SourceOverlay";
import Value from "./Value";
import SourcePills from "./SourcePills";
import { formatDate, formatRange, shortId } from "../lib/format";

// Recharts only loads when a result actually has a trend to draw.
const TrendChart = lazy(() => import("./TrendChart"));

// One analyte can have several unit series, so the unit is part of the identity.
const seriesKey = (result) =>
  `${result.analyte_id}-${result.unit || "none"}`.replace(/[^a-zA-Z0-9_-]/g, "_");

const ORGANS = { blood_immunity: "Blood & Immunity", kidneys_renal: "Kidneys", heart_lipids: "Heart & Lipids",
  sugar_metabolism: "Sugar & Metabolism", liver_digestion: "Liver", thyroid_hormones: "Thyroid",
  oncology_surgeries: "Oncology", other_general: "Other" };

function isOutOfRange(point) {
  if (["low", "high", "critical", "positive_finding"].includes(point.abnormal_flag)) return true;
  if (point.abnormal_flag === "normal") return false;
  const flag = String(point.flag_printed || "").toLowerCase();
  if (["h", "high", "l", "low", "critical", "positive"].includes(flag)) return true;
  return (point.ref_min != null && point.value < point.ref_min) ||
    (point.ref_max != null && point.value > point.ref_max);
}

export default function Results({ results = [], organGroups, onSource }) {
  const [source, setSource] = useState(null);
  const [organ, setOrgan] = useState(null);
  const [abnormalOnly, setAbnormalOnly] = useState(false);
  const openSource = onSource ?? setSource;
  const groups = Object.entries(organGroups ?? {}).filter(([, biomarkers]) => biomarkers.length);
  const selected = organ && organGroups?.[organ];
  const organFiltered = results.filter((result) => !selected || selected.some((biomarker) =>
    biomarker.analyte_id === result.analyte_id && biomarker.unit === result.unit));
  const outOfRangeCount = results.reduce((count, result) =>
    count + result.points.filter(isOutOfRange).length, 0);
  const visible = organFiltered.filter((result) => !abnormalOnly || result.points.some(isOutOfRange));
  const reviewCount = results.reduce(
    (count, result) =>
      count + result.points.filter((point) => point.status === "review").length,
    0,
  );

  return (
    <Panel title="Results">
      {groups.length ? <div className="organ-controls" role="group" aria-label="Result organ groups">
        <button type="button" className="button-secondary" aria-pressed={!organ} onClick={() => setOrgan(null)}>All</button>
        {groups.map(([key]) => <button type="button" className="button-secondary" key={key}
          aria-pressed={organ === key} onClick={() => setOrgan(key)}>{ORGANS[key] ?? "Other"}</button>)}
      </div> : null}
      <div className="result-filter-box">
        <label>
          <input
            type="checkbox"
            checked={abnormalOnly}
            onChange={(event) => setAbnormalOnly(event.target.checked)}
          />
          Only out of range <span className="count-badge">{outOfRangeCount}</span>
        </label>
      </div>
      {reviewCount > 0 ? (
        <p className="result-note" role="note">
          {reviewCount} extracted {reviewCount === 1 ? "value is" : "values are"} awaiting review in
          Documents. Open the document to accept, correct, or reject{" "}
          {reviewCount === 1 ? "it" : "them"}.
        </p>
      ) : null}
      {results.length === 0 ? (
        <p className="empty">No results recorded.</p>
      ) : visible.length === 0 ? (
        <p className="empty">No values match this filter.</p>
      ) : (
        visible.map((result) => (
          <section
            className="result"
            key={seriesKey(result)}
            aria-labelledby={`result-${seriesKey(result)}`}
          >
            <div className="result-head">
              <div>
                <h3 id={`result-${seriesKey(result)}`}>{result.display}</h3>
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
              <>
                <Suspense fallback={null}>
                  <TrendChart result={result} onSource={openSource} />
                </Suspense>
                <p className="trend-legend">
                  <span>
                    <span className="trend-legend-mark" aria-hidden="true">▲</span> Out of range
                  </span>
                  <span>Dashed line · reference range</span>
                </p>
              </>
            ) : null}

            <div className="table-wrap">
              <table
                aria-describedby={
                  result.points.some((point) => point.flag_printed)
                    ? `result-${seriesKey(result)}-flag-note`
                    : undefined
                }
              >
                <caption className="sr-only">{result.display} readings</caption>
                <thead>
                  <tr>
                    <th scope="col">Date</th>
                    <th scope="col">Value</th>
                    {result.points.some((p) => Object.hasOwn(p, "ref_min")) ? <th scope="col">Reference</th> : null}
                    <th scope="col">Page</th>
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
                        {point.status === "review" ? (
                          <span className="pill value-status">Review</span>
                        ) : null}
                        {point.abnormal_flag && !point.flag_printed ? <span className="pill">{point.abnormal_flag}</span> : null}
                      </td>
                      {result.points.some((p) => Object.hasOwn(p, "ref_min")) ? <td>{formatRange(point.ref_min, point.ref_max)}</td> : null}
                      <td>
                        <button
                          type="button"
                          className="text-button source-tab"
                          onClick={() =>
                            openSource({
                              ...point,
                              analyte: result.display,
                              pageUrl: `/api/documents/${point.document_id}/page/${point.page}`,
                            })
                          }
                          aria-label={`Open source for ${result.display} on ${formatDate(
                            point.date,
                          )}`}
                        >
                          p.{point.page}
                        </button>
                        {point.source_anchors?.length > 1 ? <SourcePills item={{ title: result.display,
                          doc_id: point.document_id, event_date: point.date,
                          source_anchors: point.source_anchors.slice(1) }} onSource={openSource} /> : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {result.points.some((point) => point.flag_printed) ? (
              <p
                className="result-note"
                id={`result-${seriesKey(result)}-flag-note`}
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
                      <span className="item-source"> Source #{shortId(item.document_id)}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </section>
        ))
      )}

      {!onSource ? <SourceOverlay source={source} onClose={() => setSource(null)} /> : null}
    </Panel>
  );
}
