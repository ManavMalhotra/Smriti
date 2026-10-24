import { useEffect, useRef, useState } from "react";
import Footer from "../components/Footer";
import PageOverlay from "../components/PageOverlay";
import { requestJson } from "../lib/api";
import { docTypeLabel, formatDate, formatRange, statusLabel } from "../lib/format";

function fieldLabel(field) {
  return field.label_raw || field.analyte_id || "Unmapped field";
}

export default function DocumentDetail({ documentId, patient, onBack, onSignOut, onSummary }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [page, setPage] = useState(1);
  const [savingId, setSavingId] = useState(null);
  const [editingId, setEditingId] = useState(null);
  const [draftValue, setDraftValue] = useState("");
  const [draftUnit, setDraftUnit] = useState("");
  const headingRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    setDetail(null);
    requestJson(`/api/documents/${documentId}`)
      .then((data) => {
        if (cancelled) return;
        setDetail(data);
        setPage(data.pages?.[0]?.page ?? 1);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Could not load the document.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [documentId]);

  useEffect(() => {
    if (detail) headingRef.current?.focus();
  }, [detail]);

  async function review(observation, payload) {
    setSavingId(observation.id);
    setError("");
    try {
      const data = await requestJson(`/api/observations/${observation.id}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      setDetail((current) => ({
        ...current,
        observations: current.observations.map((item) =>
          item.id === observation.id ? { ...item, ...data.observation } : item,
        ),
      }));
      setEditingId(null);
      onSummary?.(data.summary);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the review.");
    } finally {
      setSavingId(null);
    }
  }

  function beginCorrect(observation) {
    setEditingId(observation.id);
    setDraftValue(observation.value_num ?? observation.value_text ?? "");
    setDraftUnit(observation.unit_norm ?? observation.unit_raw ?? "");
  }

  function submitCorrection(event, observation) {
    event.preventDefault();
    review(observation, {
      action: "correct",
      value_num: draftValue,
      unit_norm: draftUnit || null,
    });
  }

  const observations = detail?.observations ?? [];
  const medications = detail?.medications ?? [];
  const pageText = detail?.page_text ?? [];
  const pages = detail?.pages ?? [];
  const currentPage = pages.find((item) => item.page === page) ?? pages[0];
  const pageBoxes = observations
    .filter((observation) => observation.page === page)
    .map((observation) => observation.bbox);
  const reviewCount = observations.filter(
    (observation) => observation.status === "review",
  ).length;

  return (
    <div className="shell">
      <div className="topbar">
        <div className="wordmark">Smriti</div>
        <div className="topbar-actions">
          <button type="button" className="text-button" onClick={onBack}>
            Back to summary
          </button>
          {onSignOut ? (
            <button type="button" className="text-button" onClick={onSignOut}>
              Sign out
            </button>
          ) : null}
        </div>
      </div>

      <main>
        <header className="page-head">
          <h1 ref={headingRef} tabIndex={-1}>
            Document review
          </h1>
          <p>
            {detail
              ? `${docTypeLabel(detail.doc_type)} for ${patient.alias}. Check each extracted value against the source page.`
              : `Document ${documentId}`}
          </p>
        </header>

        {loading ? (
          <p className="empty" role="status">
            Loading document…
          </p>
        ) : null}

        {error ? (
          <div className="alert" role="alert">
            {error}
          </div>
        ) : null}

        {detail ? (
          <>
            <section className="panel" aria-labelledby="document-meta-heading">
              <h2 id="document-meta-heading">Document</h2>
              <dl className="result-meta">
                <div>
                  <dt>Type</dt>
                  <dd>{docTypeLabel(detail.doc_type)}</dd>
                </div>
                <div>
                  <dt>Status</dt>
                  <dd>{statusLabel(detail.status)}</dd>
                </div>
                <div>
                  <dt>Date</dt>
                  <dd>{formatDate(detail.collection_date ?? detail.doc_date)}</dd>
                </div>
                <div>
                  <dt>Pages</dt>
                  <dd>{detail.page_count}</dd>
                </div>
                <div>
                  <dt>Capture</dt>
                  <dd>{detail.capture_type === "handwritten" ? "Handwritten" : "Printed"}</dd>
                </div>
                <div>
                  <dt>Review</dt>
                  <dd>{reviewCount > 0 ? `${reviewCount} fields pending` : "Complete"}</dd>
                </div>
              </dl>
            </section>

            {currentPage ? (
              <section className="panel" aria-labelledby="source-page-heading">
                <h2 id="source-page-heading">Source page</h2>
                {pages.length > 1 ? (
                  <div className="page-tabs" role="group" aria-label="Document pages">
                    {pages.map((item) => (
                      <button
                        key={item.page}
                        type="button"
                        className={item.page === page ? "page-tab page-tab-active" : "page-tab"}
                        aria-pressed={item.page === page}
                        onClick={() => setPage(item.page)}
                      >
                        Page {item.page}
                      </button>
                    ))}
                  </div>
                ) : null}
                <PageOverlay
                  src={currentPage.url}
                  alt={`Page ${currentPage.page} of the ${docTypeLabel(detail.doc_type)}`}
                  boxes={pageBoxes}
                />
                <p className="result-note">
                  Highlighted boxes mark extracted values. Images and text stay on this device.
                </p>
              </section>
            ) : null}

            <section className="panel" aria-labelledby="review-fields-heading">
              <div className="result-head">
                <div>
                  <h2 id="review-fields-heading">Extracted fields</h2>
                  <p className="result-ref">
                    {observations.length === 0
                      ? "No numeric fields were extracted from this document."
                      : "Accept, correct, or reject each field. Pending values stay marked Review."}
                  </p>
                </div>
                {reviewCount > 0 ? (
                  <span className="pill">{reviewCount} to review</span>
                ) : null}
              </div>

              {observations.length > 0 ? (
                <div className="table-wrap">
                  <table>
                    <caption className="sr-only">Extracted fields from this document</caption>
                    <thead>
                      <tr>
                        <th scope="col">Field</th>
                        <th scope="col">Value</th>
                        <th scope="col">Unit</th>
                        <th scope="col">Reference</th>
                        <th scope="col">Status</th>
                        <th scope="col">Review</th>
                      </tr>
                    </thead>
                    <tbody>
                      {observations.map((observation) => (
                        <tr key={observation.id}>
                          <td>
                            <span className="doc-type">{fieldLabel(observation)}</span>
                            {observation.analyte_id ? (
                              <span className="doc-id">{observation.analyte_id}</span>
                            ) : (
                              <span className="doc-id">Unmapped</span>
                            )}
                          </td>
                          <td className="mono">
                            {observation.value_text ?? observation.value_num ?? "—"}
                            {observation.flag_printed ? (
                              <span className="flag">{observation.flag_printed}</span>
                            ) : null}
                          </td>
                          <td>{observation.unit_norm ?? observation.unit_raw ?? "—"}</td>
                          <td>{formatRange(observation.ref_low, observation.ref_high)}</td>
                          <td>{statusLabel(observation.status)}</td>
                          <td>
                            {observation.status === "review" ? (
                              editingId === observation.id ? (
                                <form
                                  className="review-form"
                                  onSubmit={(event) => submitCorrection(event, observation)}
                                >
                                  <label htmlFor={`value-${observation.id}`}>Value</label>
                                  <input
                                    id={`value-${observation.id}`}
                                    inputMode="decimal"
                                    value={draftValue}
                                    onChange={(event) => setDraftValue(event.target.value)}
                                    required
                                  />
                                  <label htmlFor={`unit-${observation.id}`}>Unit</label>
                                  <input
                                    id={`unit-${observation.id}`}
                                    value={draftUnit}
                                    onChange={(event) => setDraftUnit(event.target.value)}
                                  />
                                  <div className="review-actions">
                                    <button
                                      type="submit"
                                      className="button-primary"
                                      disabled={savingId === observation.id}
                                    >
                                      Save
                                    </button>
                                    <button
                                      type="button"
                                      className="text-button"
                                      onClick={() => setEditingId(null)}
                                    >
                                      Cancel
                                    </button>
                                  </div>
                                </form>
                              ) : (
                                <div className="review-actions">
                                  <button
                                    type="button"
                                    className="button-secondary"
                                    onClick={() => review(observation, { action: "accept" })}
                                    disabled={
                                      savingId === observation.id || !observation.analyte_id
                                    }
                                    title={
                                      observation.analyte_id
                                        ? undefined
                                        : "Map this field before accepting it."
                                    }
                                  >
                                    Accept
                                  </button>
                                  <button
                                    type="button"
                                    className="text-button"
                                    onClick={() => beginCorrect(observation)}
                                    disabled={savingId === observation.id || !observation.analyte_id}
                                  >
                                    Correct
                                  </button>
                                  <button
                                    type="button"
                                    className="text-button"
                                    onClick={() =>
                                      review(observation, {
                                        action: "reject",
                                        reason: "Rejected during review.",
                                      })
                                    }
                                    disabled={savingId === observation.id}
                                  >
                                    Reject
                                  </button>
                                </div>
                              )
                            ) : (
                              <span className="result-note">
                                {observation.reason ?? "Reviewed."}
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
            </section>

            {medications.length > 0 ? (
              <section className="panel" aria-labelledby="review-medications-heading">
                <h2 id="review-medications-heading">Extracted medications</h2>
                <ul className="list">
                  {medications.map((medication) => (
                    <li key={medication.id}>
                      <span>{medication.brand_raw}</span>
                      <span className="unit">
                        {[medication.dose, medication.freq].filter(Boolean).join(" · ")}
                      </span>
                    </li>
                  ))}
                </ul>
                <p className="result-note">
                  Medication text is extracted for review. It is not yet reconciled with the
                  medication list.
                </p>
              </section>
            ) : null}

            {pageText.length > 0 ? (
              <section className="panel" aria-labelledby="review-text-heading">
                <h2 id="review-text-heading">Extracted text</h2>
                <details className="extracted-text">
                  <summary>Show local OCR text</summary>
                  {pageText.map((item) => (
                    <div key={item.page}>
                      <h3>Page {item.page}</h3>
                      <pre>{item.text || "No text detected."}</pre>
                    </div>
                  ))}
                </details>
              </section>
            ) : null}
          </>
        ) : null}
      </main>

      <Footer />
    </div>
  );
}
