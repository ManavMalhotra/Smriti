import { useEffect, useRef } from "react";
import PageOverlay from "./PageOverlay";
import { formatDate, shortId } from "../lib/format";

export default function SourceOverlay({ source, onClose, drawer = false }) {
  const dialogRef = useRef(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    if (!source) return;
    const previous = document.activeElement;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    function onKeyDown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        closeRef.current();
        return;
      }
      if (event.key !== "Tab") return;

      const focusable = Array.from(
        dialogRef.current?.querySelectorAll(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!dialogRef.current?.contains(document.activeElement)) {
        event.preventDefault();
        first.focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    dialogRef.current?.querySelector("[data-autofocus]")?.focus();
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      previous?.focus?.();
    };
  }, [source]);

  if (!source) return null;

  const bbox = source.bbox ?? [];
  const hasBox = bbox.length === 4;
  const [x0, y0, x1, y1] = bbox;

  return (
    <div
      className="source-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        ref={dialogRef}
        className={`source source-modal${drawer ? " source-drawer" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="source-heading"
      >
        <div className="source-head">
          <div>
            <h2 id="source-heading">Source</h2>
            <p className="source-path">
              {source.analyte
                ? `${source.analyte} · ${formatDate(source.date)}`
                : "Source page"}
            </p>
          </div>
          <button
            type="button"
            className="button-secondary"
            onClick={onClose}
            data-autofocus
          >
            Close
          </button>
        </div>

        <div className="source-body">
          {source.pageUrl ? (
            <PageOverlay
              src={source.pageUrl}
              alt={`Source page ${source.page}`}
              boxes={hasBox ? [bbox] : []}
            />
          ) : hasBox ? (
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
              Page {source.page} · document #{shortId(source.document_id)}
            </p>
            <p className="source-note">
              Highlighted region on the original page, stored on this device.
            </p>
            {source.pageUrl ? (
              <p>
                <a href={source.pageUrl} target="_blank" rel="noreferrer">
                  Open full page
                </a>
              </p>
            ) : null}
          </div>
        </div>
      </section>
    </div>
  );
}
