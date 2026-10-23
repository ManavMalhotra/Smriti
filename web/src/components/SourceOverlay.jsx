import { formatDate } from "../lib/format";

export default function SourceOverlay({ source, onClose }) {
  if (!source) return null;

  const bbox = source.bbox ?? [];
  const hasBox = bbox.length === 4;
  const [x0, y0, x1, y1] = bbox;

  return (
    <section className="source" aria-labelledby="source-heading">
      <div className="source-head">
        <div>
          <h3 id="source-heading">Source</h3>
          <p className="source-path">
            {source.analyte ? `${source.analyte} · ${formatDate(source.date)}` : "Source path"}
          </p>
        </div>
        <button
          type="button"
          className="text-button"
          onClick={onClose}
          aria-label="Close source"
        >
          Close
        </button>
      </div>

      <div className="source-body">
        {hasBox ? (
          <div
            className="source-box"
            role="img"
            aria-label={`Source box on page ${source.page}`}
          >
            <div
              className="source-box-highlight"
              style={{
                left: `${x0 * 100}%`,
                top: `${y0 * 100}%`,
                width: `${(x1 - x0) * 100}%`,
                height: `${(y1 - y0) * 100}%`,
              }}
            />
          </div>
        ) : null}

        <div>
          <p className="source-path">
            Document {source.document_id} · page {source.page}
          </p>
          {hasBox ? (
            <p className="source-coords">
              {x0.toFixed(2)}, {y0.toFixed(2)}, {x1.toFixed(2)}, {y1.toFixed(2)}
            </p>
          ) : null}
          <p className="source-note">Normalised box on the source page.</p>
          {source.pageUrl ? (
            <p>
              <a href={source.pageUrl} target="_blank" rel="noreferrer">
                Open source page
              </a>
            </p>
          ) : null}
        </div>
      </div>
    </section>
  );
}
