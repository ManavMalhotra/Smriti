import { useEffect, useRef, useState } from "react";
import Footer from "../components/Footer";
import PageOverlay from "../components/PageOverlay";
import { requestJson } from "../lib/api";
import {
  categoryLabel,
  docTypeLabel,
  engineTrustBadge,
  formatDate,
  formatRange,
  reportCategories,
  shortId,
  statusLabel,
} from "../lib/format";

function fieldLabel(field) {
  return field.label_raw || field.analyte_id || "Unmapped field";
}

function formatDateTime(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

export default function DocumentDetail({
  documentId,
  patient,
  initialPage = 1,
  onPageChange,
  onBack,
  onSignOut,
  onQueue,
  onDocuments,
  backLabel = "Back to summary",
  onSummary,
}) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [page, setPage] = useState(initialPage);
  const [offset, setOffset] = useState(0);
  const [zoom, setZoom] = useState(100);
  const [activeObsId, setActiveObsId] = useState(null);
  const [savingId, setSavingId] = useState(null);
  const [editingId, setEditingId] = useState(null);
  const [draftValue, setDraftValue] = useState("");
  const [draftUnit, setDraftUnit] = useState("");
  const [draftAnalyteId, setDraftAnalyteId] = useState("");
  const [draftRawLabel, setDraftRawLabel] = useState("");
  const [draftRefLow, setDraftRefLow] = useState("");
  const [draftRefHigh, setDraftRefHigh] = useState("");
  const [draftFlag, setDraftFlag] = useState("");

  const [showAddObs, setShowAddObs] = useState(false);
  const [newObsLabel, setNewObsLabel] = useState("");
  const [newObsAnalyteId, setNewObsAnalyteId] = useState("");
  const [newObsValue, setNewObsValue] = useState("");
  const [newObsUnit, setNewObsUnit] = useState("");
  const [newObsRefLow, setNewObsRefLow] = useState("");
  const [newObsRefHigh, setNewObsRefHigh] = useState("");
  const [newObsFlag, setNewObsFlag] = useState("");
  const [addingObs, setAddingObs] = useState(false);
  const [addObsError, setAddObsError] = useState("");

  const [editingMedId, setEditingMedId] = useState(null);
  const [draftMedBrand, setDraftMedBrand] = useState("");
  const [draftMedDose, setDraftMedDose] = useState("");
  const [draftMedFreq, setDraftMedFreq] = useState("");
  const [draftMedStatus, setDraftMedStatus] = useState("prescribed");
  const [savingMedId, setSavingMedId] = useState(null);
  const [deletingMedId, setDeletingMedId] = useState(null);
  const [medError, setMedError] = useState("");
  const [editingReportId, setEditingReportId] = useState(null);
  const [draftReportDate, setDraftReportDate] = useState("");
  const [draftReportCategory, setDraftReportCategory] = useState("other");
  const [draftReportTitle, setDraftReportTitle] = useState("");
  const [draftReportFacility, setDraftReportFacility] = useState("");
  const [savingReportId, setSavingReportId] = useState(null);
  const [quickDate, setQuickDate] = useState("");
  const [quickFacility, setQuickFacility] = useState("");
  const [quickMeds, setQuickMeds] = useState([{ name: "", dose: "", frequency: "" }]);
  const [quickSaved, setQuickSaved] = useState(false);
  const [quickSaving, setQuickSaving] = useState(false);
  const headingRef = useRef(null);

  useEffect(() => {
    setPage(initialPage);
    setOffset(0);
  }, [documentId, initialPage]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    const controller = new AbortController();
    requestJson(`/api/documents/${documentId}?page=${page}&offset=${offset}`, { signal: controller.signal })
      .then((data) => {
        if (cancelled) return;
        setDetail(data);
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
      controller.abort();
    };
  }, [documentId, patient.id, page, offset]);

  useEffect(() => {
    headingRef.current?.focus();
  }, [documentId]);

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
    setActiveObsId(observation.id);
    setDraftValue(observation.value_num ?? observation.value_text ?? "");
    setDraftUnit(observation.unit_norm ?? observation.unit_raw ?? "");
    setDraftAnalyteId(observation.analyte_id ?? "");
    setDraftRawLabel(observation.label_raw ?? observation.raw_label ?? "");
    setDraftRefLow(observation.ref_low != null ? String(observation.ref_low) : "");
    setDraftRefHigh(observation.ref_high != null ? String(observation.ref_high) : "");
    setDraftFlag(observation.flag_printed ?? "");
  }

  function submitCorrection(event, observation) {
    event.preventDefault();
    const payload =
      observation.value_num == null
        ? {
            action: "correct",
            value_text: draftValue,
            unit_norm: draftUnit || null,
          }
        : {
            action: "correct",
            value_num: draftValue,
            unit_norm: draftUnit || null,
          };
    if (draftAnalyteId.trim() && draftAnalyteId.trim() !== (observation.analyte_id || "")) {
      payload.analyte_id = draftAnalyteId.trim();
    }
    const origRawLabel = observation.label_raw ?? observation.raw_label ?? "";
    if (draftRawLabel.trim() && draftRawLabel.trim() !== origRawLabel.trim()) {
      payload.raw_label = draftRawLabel.trim();
    }
    const origRefLow = observation.ref_low != null ? Number(observation.ref_low) : null;
    const numRefLow = draftRefLow !== "" ? Number(draftRefLow) : null;
    if (numRefLow !== origRefLow) {
      payload.ref_low = numRefLow;
    }
    const origRefHigh = observation.ref_high != null ? Number(observation.ref_high) : null;
    const numRefHigh = draftRefHigh !== "" ? Number(draftRefHigh) : null;
    if (numRefHigh !== origRefHigh) {
      payload.ref_high = numRefHigh;
    }
    const origFlag = observation.flag_printed ?? "";
    if (draftFlag !== origFlag) {
      payload.flag_printed = draftFlag || null;
    }
    review(observation, payload);
  }

  async function submitManualObservation(event) {
    event.preventDefault();
    if (!newObsLabel.trim()) return;
    setAddingObs(true);
    setAddObsError("");
    try {
      const isNum = !isNaN(Number(newObsValue)) && newObsValue.trim() !== "";
      const body = {
        raw_label: newObsLabel.trim(),
        analyte_id: newObsAnalyteId.trim() || null,
        value_num: isNum ? Number(newObsValue) : null,
        value_text: !isNum && newObsValue.trim() ? newObsValue.trim() : null,
        unit_norm: newObsUnit.trim() || null,
        ref_low: newObsRefLow !== "" ? Number(newObsRefLow) : null,
        ref_high: newObsRefHigh !== "" ? Number(newObsRefHigh) : null,
        flag_printed: newObsFlag.trim() || null,
        page,
        bbox: null,
      };
      const res = await requestJson(`/api/documents/${documentId}/observations`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      setDetail((current) => ({
        ...current,
        observations: [res.observation, ...(current?.observations || [])],
      }));
      onSummary?.(res.summary);
      setShowAddObs(false);
      setNewObsLabel("");
      setNewObsAnalyteId("");
      setNewObsValue("");
      setNewObsUnit("");
      setNewObsRefLow("");
      setNewObsRefHigh("");
      setNewObsFlag("");
    } catch (err) {
      setAddObsError(err.message || "Failed to add observation.");
    } finally {
      setAddingObs(false);
    }
  }

  function beginMedEdit(med) {
    setEditingMedId(med.id);
    setDraftMedBrand(med.brand_raw || "");
    setDraftMedDose(med.dose || "");
    setDraftMedFreq(med.freq || "");
    setDraftMedStatus(med.status || "prescribed");
    setMedError("");
  }

  async function saveMedication(event, med) {
    event.preventDefault();
    setSavingMedId(med.id);
    setMedError("");
    try {
      const res = await requestJson(`/api/medications/${med.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          brand_raw: draftMedBrand || null,
          dose: draftMedDose || null,
          freq: draftMedFreq || null,
          status: draftMedStatus || null,
        }),
      });
      setDetail((curr) => ({
        ...curr,
        medications: curr.medications.map((m) => (m.id === med.id ? { ...m, ...res.medication } : m)),
      }));
      setEditingMedId(null);
      onSummary?.(res.summary);
    } catch (err) {
      setMedError(err.message || "Could not save medication.");
    } finally {
      setSavingMedId(null);
    }
  }

  async function deleteMedication(med) {
    if (!window.confirm(`Delete medication "${med.brand_raw}"?`)) return;
    setDeletingMedId(med.id);
    setMedError("");
    try {
      const res = await requestJson(`/api/medications/${med.id}`, { method: "DELETE" });
      setDetail((curr) => ({
        ...curr,
        medications: curr.medications.filter((m) => m.id !== med.id),
      }));
      onSummary?.(res.summary);
    } catch (err) {
      setMedError(err.message || "Could not delete medication.");
    } finally {
      setDeletingMedId(null);
    }
  }

  function beginReportEdit(report) {
    setEditingReportId(report.id);
    setDraftReportDate(report.report_date ?? "");
    setDraftReportCategory(report.category);
    setDraftReportTitle(report.title ?? "");
    setDraftReportFacility(report.facility_name ?? "");
  }

  async function saveReport(event, report) {
    event.preventDefault();
    setSavingReportId(report.id);
    setError("");
    try {
      const data = await requestJson(`/api/reports/${report.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          report_date: draftReportDate || null,
          category: draftReportCategory,
          title: draftReportTitle || null,
          facility_name: draftReportFacility || null,
        }),
      });
      setDetail((current) => ({
        ...current,
        reports: current.reports.map((item) =>
          item.id === report.id ? { ...item, ...data.report } : item,
        ),
      }));
      setEditingReportId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the report.");
    } finally {
      setSavingReportId(null);
    }
  }

  const observations = detail?.observations ?? [];
  const reports = detail?.reports ?? [];
  const medications = detail?.medications ?? [];
  const pages = detail?.pages ?? [];
  const currentPage = pages.find((item) => item.page === page) ?? pages[0];
  const pageBoxes = observations
    .filter((observation) => observation.page === page)
    .map((observation) => observation.bbox);
  const activeObservation = observations.find((obs) => obs.id === activeObsId);
  const activeBox =
    activeObservation && activeObservation.page === page ? activeObservation.bbox : null;

  const reviewCount = observations.filter(
    (observation) => observation.status === "review",
  ).length;
  const changingDisabled = Boolean(savingId || savingReportId || editingId || editingReportId);
  const needsHumanReview = detail?.capture_type === "handwritten" || reports.some((report) =>
    report.status === "review" && page >= report.page_start && page <= report.page_end && /handwrit|low-confidence/i.test(report.reason || ""));

  async function saveQuickEntry(event) {
    event.preventDefault();
    setQuickSaving(true);
    setError("");
    try {
      await requestJson(`/api/documents/${documentId}/quick-entry`, { method: "POST", body: JSON.stringify({
        doc_type: "prescription", doc_date: quickDate || null, facility_name: quickFacility,
        medications: quickMeds.filter((med) => med.name.trim()).map((med) => ({ ...med, page })),
      }) });
      const updatedSummary = await requestJson(`/api/patients/${patient.id}/summary`);
      onSummary?.(updatedSummary);
      setQuickSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the handwritten details.");
    } finally { setQuickSaving(false); }
  }

  function changePage(next) {
    setPage(next);
    setOffset(0);
    setActiveObsId(null);
    onPageChange?.(next);
  }

  return (
    <div className="shell review-shell">
      <div className="topbar">
        <div className="wordmark">Smriti</div>
        <div className="topbar-actions">
          <button type="button" className="text-button" onClick={onBack}>
            {backLabel}
          </button>
          {onDocuments ? <button type="button" className="text-button" onClick={onDocuments}>Documents</button> : null}
          {onQueue ? <button type="button" className="text-button" onClick={onQueue}>Queue</button> : null}
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
              ? `${detail.display_name || docTypeLabel(detail.doc_type)} for ${patient.alias}. Check each extracted value against the source page.`
              : `Document #${shortId(documentId)}`}
          </p>
        </header>

        {loading && !detail ? (
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
          <div className="workbench">
            {/* LEFT COLUMN: Zoomable Source Document Image */}
            <div className="workbench-viewer-col">
              {currentPage ? (
                <section className="panel workbench-viewer-panel" aria-labelledby="source-page-heading">
                  <div className="viewer-toolbar">
                    <div className="viewer-title-row">
                      <h2 id="source-page-heading" className="eyebrow">
                        Source Page {currentPage.page} of {detail.page_count}
                      </h2>
                      <div className="zoom-controls" role="group" aria-label="Image zoom">
                        <button
                          type="button"
                          className="zoom-btn"
                          onClick={() => setZoom((z) => Math.max(50, z - 25))}
                          aria-label="Zoom out"
                          title="Zoom out"
                        >
                          −
                        </button>
                        <span className="zoom-text">{zoom}%</span>
                        <button
                          type="button"
                          className="zoom-btn"
                          onClick={() => setZoom((z) => Math.min(300, z + 25))}
                          aria-label="Zoom in"
                          title="Zoom in"
                        >
                          +
                        </button>
                        <button
                          type="button"
                          className="zoom-btn zoom-btn-reset"
                          onClick={() => setZoom(100)}
                          aria-label="Reset zoom"
                          title="Reset zoom"
                        >
                          100%
                        </button>
                      </div>
                    </div>

                    {detail.detail_page != null && detail.page_count > 1 ? (
                      <div className="page-tabs" role="group" aria-label="Document pages">
                        <button type="button" className="button-secondary" disabled={page <= 1 || changingDisabled} onClick={() => changePage(page - 1)}>Previous page</button>
                        <label htmlFor="source-page">Page</label>
                        <input id="source-page" type="number" min="1" max={detail.page_count} value={page} disabled={changingDisabled}
                          onChange={(event) => {
                            const next = Number(event.target.value);
                            if (Number.isInteger(next) && next >= 1 && next <= detail.page_count) changePage(next);
                          }} />
                        <button type="button" className="button-secondary" disabled={page >= detail.page_count || changingDisabled} onClick={() => changePage(page + 1)}>Next page</button>
                      </div>
                    ) : pages.length > 1 ? (
                      <div className="page-tabs" role="group" aria-label="Document pages">
                        {pages.map((item) => (
                          <button
                            key={item.page}
                            type="button"
                            className={item.page === page ? "page-tab page-tab-active" : "page-tab"}
                            aria-pressed={item.page === page}
                            onClick={() => changePage(item.page)}
                          >
                            Page {item.page}
                          </button>
                        ))}
                      </div>
                    ) : null}
                  </div>

                  <div className="viewer-scroll-area">
                    <div
                      className="viewer-scale-container"
                      style={{
                        transform: `scale(${zoom / 100})`,
                        transformOrigin: "top left",
                        width: `${100 * (100 / zoom)}%`,
                      }}
                    >
                      <PageOverlay
                        src={currentPage.url}
                        alt={`Page ${currentPage.page} of the ${docTypeLabel(detail.doc_type)}`}
                        boxes={pageBoxes}
                        activeBox={activeBox}
                      />
                    </div>
                  </div>

                  <div className="viewer-foot">
                    <span className="result-note">
                      Highlighted boxes mark extracted values.
                    </span>
                    <a href={currentPage.url} target="_blank" rel="noreferrer" className="text-button">
                      Open full image ↗
                    </a>
                  </div>
                </section>
              ) : null}
            </div>

            {/* RIGHT COLUMN: Extracted Values, Actions & Document Details */}
            <div className="workbench-details-col">
              {needsHumanReview ? <section className="panel handwritten-entry" aria-labelledby="handwritten-heading">
                <h2 id="handwritten-heading">Handwritten page · enter what you can read</h2>
                <p className="result-note">Cursive text is left for human review. Save only details you can verify from the page.</p>
                {quickSaved ? <p className="success-note" role="status">Your verified details were saved.</p> : <form className="review-form" onSubmit={saveQuickEntry}>
                  <p className="item-meta">Document type · Prescription</p>
                  <label htmlFor="quick-date">Document date</label><input id="quick-date" type="date" value={quickDate} onChange={(event) => setQuickDate(event.target.value)} />
                  <label htmlFor="quick-facility">Doctor or clinic</label><input id="quick-facility" maxLength={160} value={quickFacility} onChange={(event) => setQuickFacility(event.target.value)} />
                  {quickMeds.map((med, i) => <fieldset className="quick-med-entry" key={i}><legend>Medicine {i + 1}</legend>
                    <label htmlFor={`quick-medicine-${i}`}>Medicine name</label><input id={`quick-medicine-${i}`} maxLength={160} value={med.name} onChange={(event) => setQuickMeds((items) => items.map((item, j) => j === i ? { ...item, name: event.target.value } : item))} />
                    <div className="form-grid two"><div><label htmlFor={`quick-dose-${i}`}>Dose</label><input id={`quick-dose-${i}`} maxLength={100} value={med.dose} onChange={(event) => setQuickMeds((items) => items.map((item, j) => j === i ? { ...item, dose: event.target.value } : item))} /></div>
                      <div><label htmlFor={`quick-frequency-${i}`}>How often</label><input id={`quick-frequency-${i}`} maxLength={100} value={med.frequency} onChange={(event) => setQuickMeds((items) => items.map((item, j) => j === i ? { ...item, frequency: event.target.value } : item))} /></div></div>
                    {quickMeds.length > 1 ? <button type="button" className="text-button" onClick={() => setQuickMeds((items) => items.filter((_, j) => j !== i))}>Remove medicine</button> : null}
                  </fieldset>)}
                  <button type="button" className="text-button" onClick={() => setQuickMeds((items) => [...items, { name: "", dose: "", frequency: "" }])}>Add another medicine</button>
                  <button className="button-primary" type="submit" disabled={quickSaving}>{quickSaving ? "Saving…" : "Save verified details"}</button>
                </form>}
              </section> : null}
              <section className="panel" aria-labelledby="review-fields-heading">
                <div className="result-head">
                  <div>
                    <h2 id="review-fields-heading">Extracted fields</h2>
                    <p className="result-ref">
                      {observations.length === 0
                        ? "No numeric fields were extracted from this document."
                        : "Accept, correct, or reject each field against the source document."}
                    </p>
                  </div>
                  <div className="button-group">
                    <button
                      type="button"
                      className="button-secondary"
                      onClick={() => setShowAddObs((v) => !v)}
                    >
                      {showAddObs ? "Cancel" : "+ Add Missing Lab / Finding"}
                    </button>
                    {reviewCount > 0 ? (
                      <span className="pill">{reviewCount} to review</span>
                    ) : null}
                  </div>
                </div>

                {showAddObs ? (
                  <form className="review-form manual-entry-panel" onSubmit={submitManualObservation}>
                    <h3>Add verified lab finding</h3>
                    <div className="form-grid two">
                      <div>
                        <label htmlFor="new-obs-label">Test name</label>
                        <input
                          id="new-obs-label"
                          value={newObsLabel}
                          placeholder="e.g. Hemoglobin, Fasting Blood Sugar"
                          onChange={(e) => setNewObsLabel(e.target.value)}
                          required
                        />
                      </div>
                      <div>
                        <label htmlFor="new-obs-analyte">Analyte ID (optional)</label>
                        <input
                          id="new-obs-analyte"
                          value={newObsAnalyteId}
                          placeholder="e.g. hemoglobin, fasting_glucose"
                          onChange={(e) => setNewObsAnalyteId(e.target.value)}
                        />
                      </div>
                    </div>
                    <div className="form-grid two">
                      <div>
                        <label htmlFor="new-obs-value">Value</label>
                        <input
                          id="new-obs-value"
                          value={newObsValue}
                          placeholder="e.g. 13.5"
                          onChange={(e) => setNewObsValue(e.target.value)}
                          required
                        />
                      </div>
                      <div>
                        <label htmlFor="new-obs-unit">Unit</label>
                        <input
                          id="new-obs-unit"
                          value={newObsUnit}
                          placeholder="e.g. g/dL, mg/dL"
                          onChange={(e) => setNewObsUnit(e.target.value)}
                        />
                      </div>
                    </div>
                    <div className="form-grid two">
                      <div>
                        <label htmlFor="new-obs-ref-low">Reference low</label>
                        <input
                          id="new-obs-ref-low"
                          type="number"
                          step="any"
                          value={newObsRefLow}
                          placeholder="e.g. 12.0"
                          onChange={(e) => setNewObsRefLow(e.target.value)}
                        />
                      </div>
                      <div>
                        <label htmlFor="new-obs-ref-high">Reference high</label>
                        <input
                          id="new-obs-ref-high"
                          type="number"
                          step="any"
                          value={newObsRefHigh}
                          placeholder="e.g. 16.0"
                          onChange={(e) => setNewObsRefHigh(e.target.value)}
                        />
                      </div>
                    </div>
                    <label htmlFor="new-obs-flag">Flag</label>
                    <select
                      id="new-obs-flag"
                      value={newObsFlag}
                      onChange={(e) => setNewObsFlag(e.target.value)}
                    >
                      <option value="">Normal / None</option>
                      <option value="H">High (H)</option>
                      <option value="L">Low (L)</option>
                      <option value="Critical">Critical</option>
                    </select>
                    {addObsError ? <p className="alert" role="alert">{addObsError}</p> : null}
                    <div className="review-actions">
                      <button type="submit" className="button-primary" disabled={addingObs}>
                        {addingObs ? "Adding…" : "Add finding"}
                      </button>
                      <button type="button" className="text-button" onClick={() => setShowAddObs(false)}>
                        Cancel
                      </button>
                    </div>
                  </form>
                ) : null}

                {needsHumanReview ? <p className="empty">Automated fields are hidden for this page. Use the source page and enter verified details above.</p> : observations.length > 0 ? (
                  <div className="table-wrap">
                    <table className="review-table">
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
                        {observations.map((observation) => {
                          const isSelected = activeObsId === observation.id;
                          const trust = engineTrustBadge(observation.engine, observation.status, observation.engine === "human");
                          return (
                            <tr
                              key={observation.id}
                              className={isSelected ? "review-row-active" : undefined}
                              onMouseEnter={() => {
                                setActiveObsId(observation.id);
                                if (observation.page && observation.page !== page) {
                                  changePage(observation.page);
                                }
                              }}
                              onClick={() => {
                                setActiveObsId(observation.id);
                                if (observation.page && observation.page !== page) {
                                  changePage(observation.page);
                                }
                              }}
                            >
                              <td className="field-cell" data-label="Field">
                                <div className="timeline-title">
                                  <span className="doc-type">{fieldLabel(observation)}</span>
                                  <span className={`trust-badge ${trust.className}`}>{trust.label}</span>
                                </div>
                                {!observation.analyte_id && observation.value_num != null ? (
                                  <span className="doc-id">
                                    Not linked to a standard test; reject only.
                                  </span>
                                ) : null}
                              </td>
                              <td className="value-cell" data-label="Value">
                                <span className="mono">
                                  {observation.value_text ?? observation.value_num ?? "—"}
                                </span>
                                {observation.flag_printed ? (
                                  <span className="flag">{observation.flag_printed}</span>
                                ) : null}
                              </td>
                              <td className="unit-cell" data-label="Unit">
                                {observation.unit_norm ?? observation.unit_raw ?? "—"}
                              </td>
                              <td className="ref-cell" data-label="Reference">
                                {formatRange(observation.ref_low, observation.ref_high)}
                              </td>
                              <td className="status-cell" data-label="Status">
                                {statusLabel(observation.status)}
                              </td>
                              <td className="review-cell" data-label="Review">
                                {observation.status === "review" ? (
                                  editingId === observation.id ? (
                                    <form
                                      className="review-form"
                                      onSubmit={(event) => submitCorrection(event, observation)}
                                    >
                                      <label htmlFor={`value-${observation.id}`}>Value</label>
                                      <input
                                        id={`value-${observation.id}`}
                                        inputMode={
                                          observation.value_num == null ? "text" : "decimal"
                                        }
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
                                      <label htmlFor={`raw-label-${observation.id}`}>Test label</label>
                                      <input
                                        id={`raw-label-${observation.id}`}
                                        value={draftRawLabel}
                                        onChange={(event) => setDraftRawLabel(event.target.value)}
                                      />
                                      {!observation.analyte_id ? (
                                        <>
                                          <label htmlFor={`analyte-${observation.id}`}>Analyte ID</label>
                                          <input
                                            id={`analyte-${observation.id}`}
                                            value={draftAnalyteId}
                                            placeholder="e.g. hba1c, glucose"
                                            onChange={(event) => setDraftAnalyteId(event.target.value)}
                                          />
                                        </>
                                      ) : null}
                                      <div className="form-grid two">
                                        <div>
                                          <label htmlFor={`ref-low-${observation.id}`}>Reference low</label>
                                          <input
                                            id={`ref-low-${observation.id}`}
                                            type="number"
                                            step="any"
                                            value={draftRefLow}
                                            onChange={(event) => setDraftRefLow(event.target.value)}
                                          />
                                        </div>
                                        <div>
                                          <label htmlFor={`ref-high-${observation.id}`}>Reference high</label>
                                          <input
                                            id={`ref-high-${observation.id}`}
                                            type="number"
                                            step="any"
                                            value={draftRefHigh}
                                            onChange={(event) => setDraftRefHigh(event.target.value)}
                                          />
                                        </div>
                                      </div>
                                      <label htmlFor={`flag-${observation.id}`}>Flag</label>
                                      <select
                                        id={`flag-${observation.id}`}
                                        value={draftFlag}
                                        onChange={(event) => setDraftFlag(event.target.value)}
                                      >
                                        <option value="">Normal / None</option>
                                        <option value="H">High (H)</option>
                                        <option value="L">Low (L)</option>
                                        <option value="Critical">Critical</option>
                                      </select>
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
                                          savingId === observation.id ||
                                          (!observation.analyte_id && observation.value_num != null)
                                        }
                                        title={
                                          observation.analyte_id || observation.value_num == null
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
                                        disabled={
                                          savingId === observation.id ||
                                          (!observation.analyte_id &&
                                            observation.value_num != null)
                                        }
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
                                    {observation.status === "rejected"
                                      ? observation.reason ?? "Rejected."
                                      : "—"}
                                  </span>
                                )}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                ) : null}
                {detail.has_more || offset > 0 ? (
                  <div className="form-actions" role="group" aria-label="Result ranges">
                    <button type="button" className="button-secondary" disabled={offset === 0 || changingDisabled} onClick={() => setOffset(Math.max(0, offset - 100))}>Previous results</button>
                    <button type="button" className="button-secondary" disabled={!detail.has_more || changingDisabled} onClick={() => setOffset(offset + 100)}>Next results</button>
                  </div>
                ) : null}
              </section>

              {reports.length > 0 ? (
                <section className="panel" aria-labelledby="reports-heading">
                  <h2 id="reports-heading">Reports in this document</h2>
                  <ul className="list">
                    {reports.map((report) => (
                      <li key={report.id}>
                        <div className="timeline-title">
                          <span>{report.title || categoryLabel(report.category)}</span>
                          <span className="pill">{categoryLabel(report.category)}</span>
                          {report.status === "review" ? (
                            <span className="pill">Review</span>
                          ) : null}
                        </div>
                        <p className="result-note">
                          {[
                            formatDate(report.report_date),
                            report.facility_name,
                            report.page_start === report.page_end
                              ? `Page ${report.page_start}`
                              : `Pages ${report.page_start}–${report.page_end}`,
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        </p>
                        {report.summary ? (
                          <p className="timeline-summary">{report.summary}</p>
                        ) : null}
                        {editingReportId === report.id ? (
                          <form
                            className="review-form"
                            onSubmit={(event) => saveReport(event, report)}
                          >
                            <label htmlFor={`report-date-${report.id}`}>Date</label>
                            <input
                              id={`report-date-${report.id}`}
                              type="date"
                              value={draftReportDate}
                              onChange={(event) =>
                                setDraftReportDate(event.target.value)
                              }
                            />
                            <label htmlFor={`report-category-${report.id}`}>
                              Category
                            </label>
                            <select
                              id={`report-category-${report.id}`}
                              value={draftReportCategory}
                              onChange={(event) =>
                                setDraftReportCategory(event.target.value)
                              }
                            >
                              {reportCategories.map((category) => (
                                <option key={category} value={category}>
                                  {categoryLabel(category)}
                                </option>
                              ))}
                            </select>
                            <label htmlFor={`report-title-${report.id}`}>Title</label>
                            <input
                              id={`report-title-${report.id}`}
                              type="text"
                              value={draftReportTitle}
                              onChange={(event) =>
                                setDraftReportTitle(event.target.value)
                              }
                            />
                            <label htmlFor={`report-facility-${report.id}`}>
                              Facility
                            </label>
                            <input
                              id={`report-facility-${report.id}`}
                              type="text"
                              value={draftReportFacility}
                              onChange={(event) =>
                                setDraftReportFacility(event.target.value)
                              }
                            />
                            <div className="review-actions">
                              <button
                                type="submit"
                                className="button-primary"
                                disabled={savingReportId === report.id}
                              >
                                Save report
                              </button>
                              <button
                                type="button"
                                className="text-button"
                                onClick={() => setEditingReportId(null)}
                              >
                                Cancel
                              </button>
                            </div>
                          </form>
                        ) : (
                          <div className="review-actions">
                            <button
                              type="button"
                              className="text-button"
                              onClick={() => {
                                changePage(report.page_start);
                                setActiveObsId(null);
                              }}
                            >
                              View page
                            </button>
                            <button
                              type="button"
                              className="text-button"
                              onClick={() => beginReportEdit(report)}
                            >
                              Edit date and category
                            </button>
                          </div>
                        )}
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}

              {medications.length > 0 ? (
                <section className="panel" aria-labelledby="review-medications-heading">
                  <h2 id="review-medications-heading">Extracted medications</h2>
                  {medError ? <p className="alert" role="alert">{medError}</p> : null}
                  <ul className="list">
                    {medications.map((medication) => {
                      const trust = engineTrustBadge(medication.engine, medication.status, medication.engine === "human");
                      return (
                        <li key={medication.id}>
                          {editingMedId === medication.id ? (
                            <form className="review-form" onSubmit={(event) => saveMedication(event, medication)}>
                              <label htmlFor={`med-brand-${medication.id}`}>Medicine name</label>
                              <input
                                id={`med-brand-${medication.id}`}
                                value={draftMedBrand}
                                onChange={(e) => setDraftMedBrand(e.target.value)}
                                required
                              />
                              <div className="form-grid two">
                                <div>
                                  <label htmlFor={`med-dose-${medication.id}`}>Dose</label>
                                  <input
                                    id={`med-dose-${medication.id}`}
                                    value={draftMedDose}
                                    onChange={(e) => setDraftMedDose(e.target.value)}
                                  />
                                </div>
                                <div>
                                  <label htmlFor={`med-freq-${medication.id}`}>Frequency</label>
                                  <input
                                    id={`med-freq-${medication.id}`}
                                    value={draftMedFreq}
                                    onChange={(e) => setDraftMedFreq(e.target.value)}
                                  />
                                </div>
                              </div>
                              <label htmlFor={`med-status-${medication.id}`}>Status</label>
                              <select
                                id={`med-status-${medication.id}`}
                                value={draftMedStatus}
                                onChange={(e) => setDraftMedStatus(e.target.value)}
                              >
                                <option value="prescribed">Prescribed</option>
                                <option value="reported_ongoing">Reported ongoing</option>
                                <option value="reported_stopped">Reported stopped</option>
                                <option value="discontinued">Discontinued</option>
                              </select>
                              <div className="review-actions">
                                <button type="submit" className="button-primary" disabled={savingMedId === medication.id}>
                                  {savingMedId === medication.id ? "Saving…" : "Save"}
                                </button>
                                <button type="button" className="text-button" onClick={() => setEditingMedId(null)}>
                                  Cancel
                                </button>
                              </div>
                            </form>
                          ) : (
                            <div>
                              <div className="timeline-title">
                                <strong>{medication.brand_raw}</strong>
                                <span className={`trust-badge ${trust.className}`}>{trust.label}</span>
                              </div>
                              <span className="unit">
                                {[medication.dose, medication.freq].filter(Boolean).join(" · ")}
                              </span>
                              <div className="med-card-actions">
                                <button type="button" className="text-button" onClick={() => beginMedEdit(medication)}>
                                  Edit
                                </button>
                                <button
                                  type="button"
                                  className="text-button text-danger"
                                  disabled={deletingMedId === medication.id}
                                  onClick={() => deleteMedication(medication)}
                                >
                                  {deletingMedId === medication.id ? "Deleting…" : "Delete"}
                                </button>
                              </div>
                            </div>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                </section>
              ) : null}

              <section className="panel" aria-labelledby="document-meta-heading">
                <h2 id="document-meta-heading">Document metadata</h2>
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
                    <dd>
                      {formatDate(
                        detail.verified_date ??
                          detail.collection_date ??
                          detail.registration_date ??
                          detail.report_date ??
                          detail.doc_date,
                      )}
                    </dd>
                  </div>
                  {detail.facility_name || detail.lab_name ? (
                    <div>
                      <dt>Facility</dt>
                      <dd>{detail.facility_name ?? detail.lab_name}</dd>
                    </div>
                  ) : null}
                  {detail.patient_uhid ? (
                    <div>
                      <dt>UHID / MRD</dt>
                      <dd>{detail.patient_uhid}</dd>
                    </div>
                  ) : null}
                  <div>
                    <dt>Pages</dt>
                    <dd>{detail.page_count}</dd>
                  </div>
                  <div>
                    <dt>Capture</dt>
                    <dd>{detail.capture_type === "handwritten" ? "Handwritten" : "Printed"}</dd>
                  </div>
                </dl>
              </section>

              {detail.processing_runs?.length ? <section className="panel" aria-labelledby="processing-history-heading">
                <h2 id="processing-history-heading">Processing history</h2>
                <details>
                  <summary>{detail.processing_runs.length} {detail.processing_runs.length === 1 ? "processing run" : "processing runs"}</summary>
                  <ol className="processing-run-list">{detail.processing_runs.slice().reverse().map((run) => <li key={run.number}>
                    <strong>Run {run.number}</strong><p className="result-note">Started {formatDateTime(run.started_at)}{run.finished_at ? ` · finished ${formatDateTime(run.finished_at)}` : " · still running"}</p>
                    {run.model ? <p className="result-note">Pipeline: {run.model}{run.elapsed_seconds != null ? ` · ${Math.round(run.elapsed_seconds)} sec` : ""}</p> : null}
                    {run.events.length ? <ul className="processing-event-list">{run.events.map((event, index) => <li key={`${event.timestamp}-${index}`}>
                      <span>{formatDateTime(event.timestamp)}</span> · {event.message}{event.page ? ` · page ${event.page}` : ""}
                    </li>)}</ul> : null}
                  </li>)}</ol>
                </details>
              </section> : null}

              <section className="panel" aria-labelledby="audit-logs-heading">
                <h2 id="audit-logs-heading">Audit & Cloud Review Logs</h2>
                {detail.egress?.length > 0 ? (
                  <table className="egress-table">
                    <thead>
                      <tr>
                        <th>Time</th>
                        <th>Model</th>
                        <th>Payload SHA-256</th>
                        <th>Outcome</th>
                      </tr>
                    </thead>
                    <tbody>
                      {detail.egress.map((log) => (
                        <tr key={log.id}>
                          <td>{formatDate(log.ts)}</td>
                          <td>{log.model_id || "gemini-3.8-flash-high"}</td>
                          <td title={log.payload_sha256}>{log.payload_sha256?.slice(0, 12)}…</td>
                          <td>
                            <span className={`egress-outcome ${log.outcome}`}>
                              {log.outcome}{log.reason ? ` (${log.reason})` : ""}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <p className="empty">No cloud egress events. All processing for this document remained strictly on local device.</p>
                )}
              </section>
            </div>
          </div>
        ) : null}
      </main>

      <Footer />
    </div>
  );
}
