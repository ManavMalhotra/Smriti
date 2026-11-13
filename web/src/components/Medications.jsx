import { useState } from "react";
import Panel from "./Panel";
import SourcePills from "./SourcePills";
import { engineTrustBadge, formatDate } from "../lib/format";

const STATES = [
  ["prescribed", "Prescribed"],
  ["reported_ongoing", "Reported ongoing"],
  ["reported_stopped", "Reported stopped"],
];
const ACTIVE_LIMIT = 5;

function MedicationRow({ med, onSource, onOpenDocument }) {
  const trust = engineTrustBadge(med.engine, med.status, med.engine === "human");
  const aiAssisted = Boolean(
    med.engine?.startsWith("gemini") || med.confidence_note === "deciphered_handwriting",
  );
  return (
    <li>
      <div className="timeline-title">
        <p className="item-title">
          {med.brand_raw}
          {med.salt ? ` (${med.salt})` : ""}
        </p>
        <span className={`trust-badge ${trust.className}`}>{trust.label}</span>
      </div>
      <p className="item-meta">
        {[med.dose, med.freq].filter(Boolean).join(" · ") || "Dose not recorded"}
      </p>
      {aiAssisted ? (
        <span className="pill">
          {med.confidence_note === "deciphered_handwriting"
            ? "Deciphered handwriting · check source"
            : "AI extraction · check source"}
        </span>
      ) : null}
      {med.source_doc_id || med.doc_id ? (
        <button
          type="button"
          className="text-button item-source"
          onClick={() =>
            onOpenDocument?.(med.source_doc_id || med.doc_id, med.page_num || med.page || 1)
          }
        >
          Source · page {med.page_num || med.page || 1}
        </button>
      ) : null}
      <SourcePills item={med} onSource={onSource} />
    </li>
  );
}

function ScheduleBadge({ freq, dose }) {
  if (!freq && !dose) return <span className="pill">As advised</span>;
  const timing = freq?.match(/\b(before\s+breakfast|after\s+food|before\s+food|at\s+bedtime|with\s+meals)\b/i);
  const timingText = timing ? ` · ${timing[0]}` : "";
  return (
    <span className="pill schedule-badge">
      <strong>{freq || "Regular"}</strong>
      {timingText}
    </span>
  );
}

export default function Medications({
  medications = [],
  documents = [],
  timeline,
  onSource,
  onOpenDocument,
  onSummaryUpdate,
  title,
}) {
  const [expanded, setExpanded] = useState(false);
  const [showAddModal, setShowAddModal] = useState(false);
  const [editingMed, setEditingMed] = useState(null);
  const [busyId, setBusyId] = useState(null);

  // Form state
  const [formName, setFormName] = useState("");
  const [formDose, setFormDose] = useState("");
  const [formFreq, setFormFreq] = useState("1-0-1");
  const [formDuration, setFormDuration] = useState("3 Months");
  const [formPrescribedBy, setFormPrescribedBy] = useState("");
  const [formDate, setFormDate] = useState(new Date().toISOString().slice(0, 10));
  const [formDocId, setFormDocId] = useState("");
  const [formStatus, setFormStatus] = useState("prescribed");

  const panelTitle = title || "Medications on record";

  const handleOpenAdd = (med = null) => {
    if (med) {
      setEditingMed(med);
      setFormName(med.brand_raw || "");
      setFormDose(med.dose || "");
      setFormFreq(med.freq || "OD");
      setFormDuration(med.clinical_metadata?.duration || "3 Months");
      setFormPrescribedBy(med.clinical_metadata?.prescribed_by || "");
      setFormDate(med.start_date || med.event_date || new Date().toISOString().slice(0, 10));
      setFormDocId(med.source_doc_id || "");
      setFormStatus(med.state || med.status || "prescribed");
    } else {
      setEditingMed(null);
      setFormName("");
      setFormDose("");
      setFormFreq("1-0-1");
      setFormDuration("3 Months");
      setFormPrescribedBy("");
      setFormDate(new Date().toISOString().slice(0, 10));
      setFormDocId(documents[0]?.id || "");
      setFormStatus("prescribed");
    }
    setShowAddModal(true);
  };

  const handleSavePrescription = async (e) => {
    e.preventDefault();
    if (!formName.trim()) return;

    try {
      const payload = {
        brand_raw: formName.trim(),
        dose: formDose.trim() || null,
        freq: formFreq.trim() || null,
        duration: formDuration.trim() || null,
        prescribed_by: formPrescribedBy.trim() || null,
        start_date: formDate || null,
        source_doc_id: formDocId || null,
        status: formStatus,
      };

      let res;
      if (editingMed) {
        res = await fetch(`/api/medications/${editingMed.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
      } else {
        res = await fetch("/api/medications", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
      }

      if (res.ok) {
        const data = await res.json();
        if (data.summary && onSummaryUpdate) {
          onSummaryUpdate(data.summary);
        }
        setShowAddModal(false);
      }
    } catch {
      // Best-effort network handling
    }
  };

  const handleStatusToggle = async (med, nextStatus) => {
    setBusyId(med.id);
    try {
      const res = await fetch(`/api/medications/${med.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: nextStatus }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.summary && onSummaryUpdate) {
          onSummaryUpdate(data.summary);
        }
      }
    } finally {
      setBusyId(null);
    }
  };

  const handleDeleteMedication = async (medId) => {
    if (!window.confirm("Remove this prescription from records?")) return;
    setBusyId(medId);
    try {
      const res = await fetch(`/api/medications/${medId}`, { method: "DELETE" });
      if (res.ok) {
        const data = await res.json();
        if (data.summary && onSummaryUpdate) {
          onSummaryUpdate(data.summary);
        }
      }
    } finally {
      setBusyId(null);
    }
  };

  const renderAddModal = () =>
    showAddModal ? (
      <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="rx-modal-title">
        <div className="modal-card">
          <h3 id="rx-modal-title">{editingMed ? "Edit Prescription" : "Add Doctor Prescription"}</h3>
          <form onSubmit={handleSavePrescription}>
            <div className="form-group">
              <label htmlFor="rx-form-name">Medicine Name & Strength *</label>
              <input
                id="rx-form-name"
                type="text"
                required
                placeholder="e.g. Tab. Thyronorm 50mcg or Metformin 500mg"
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
              />
            </div>

            <div className="form-row" style={{ display: "flex", gap: "12px" }}>
              <div className="form-group" style={{ flex: 1 }}>
                <label htmlFor="rx-form-dose">Dose</label>
                <input
                  id="rx-form-dose"
                  type="text"
                  placeholder="e.g. 500 mg, 1 Tab"
                  value={formDose}
                  onChange={(e) => setFormDose(e.target.value)}
                />
              </div>
              <div className="form-group" style={{ flex: 1 }}>
                <label htmlFor="rx-form-freq">Schedule / Timing</label>
                <input
                  id="rx-form-freq"
                  type="text"
                  placeholder="e.g. 1-0-1 Before Breakfast, OD, BD"
                  value={formFreq}
                  onChange={(e) => setFormFreq(e.target.value)}
                />
              </div>
            </div>

            <div className="form-row" style={{ display: "flex", gap: "12px" }}>
              <div className="form-group" style={{ flex: 1 }}>
                <label htmlFor="rx-form-dur">Duration</label>
                <input
                  id="rx-form-dur"
                  type="text"
                  placeholder="e.g. 3 Months, 15 Days"
                  value={formDuration}
                  onChange={(e) => setFormDuration(e.target.value)}
                />
              </div>
              <div className="form-group" style={{ flex: 1 }}>
                <label htmlFor="rx-form-doctor">Prescribed By</label>
                <input
                  id="rx-form-doctor"
                  type="text"
                  placeholder="e.g. Dr. Sharma, Endocrine Clinic"
                  value={formPrescribedBy}
                  onChange={(e) => setFormPrescribedBy(e.target.value)}
                />
              </div>
            </div>

            <div className="form-row" style={{ display: "flex", gap: "12px" }}>
              <div className="form-group" style={{ flex: 1 }}>
                <label htmlFor="rx-form-date">Start / Prescription Date</label>
                <input
                  id="rx-form-date"
                  type="date"
                  value={formDate}
                  onChange={(e) => setFormDate(e.target.value)}
                />
              </div>
              <div className="form-group" style={{ flex: 1 }}>
                <label htmlFor="rx-form-status">Initial Status</label>
                <select
                  id="rx-form-status"
                  value={formStatus}
                  onChange={(e) => setFormStatus(e.target.value)}
                >
                  <option value="prescribed">Active (Regular)</option>
                  <option value="reported_ongoing">SOS (As-needed)</option>
                  <option value="reported_stopped">Completed / Stopped</option>
                </select>
              </div>
            </div>

            {documents.length > 0 ? (
              <div className="form-group">
                <label htmlFor="rx-form-doc">Linked Source Document</label>
                <select
                  id="rx-form-doc"
                  value={formDocId}
                  onChange={(e) => setFormDocId(e.target.value)}
                >
                  <option value="">Standalone entry (No document link)</option>
                  {documents.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.facility_name || d.display_name || d.doc_type} ({formatDate(d.doc_date || d.collection_date)})
                    </option>
                  ))}
                </select>
              </div>
            ) : null}

            <div className="modal-actions" style={{ display: "flex", justifyContent: "flex-end", gap: "8px", marginTop: "16px" }}>
              <button type="button" className="button-secondary" onClick={() => setShowAddModal(false)}>
                Cancel
              </button>
              <button type="submit" className="button-primary">
                {editingMed ? "Update Prescription" : "Save Prescription"}
              </button>
            </div>
          </form>
        </div>
      </div>
    ) : null;

  if (timeline && Object.values(timeline).some((items) => items?.length)) {
    const active = timeline.active_scheduled ?? [];
    const rest = [
      ["conditional_sos_or", "As-needed prescriptions"],
      ["historical_completed", "Earlier prescriptions"],
    ].filter(([key]) => timeline[key]?.length);
    return (
      <Panel title={panelTitle}>
        <div className="section-head-actions" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
          <p className="result-note" style={{ margin: 0 }}>A prescription does not confirm current use.</p>
          <button
            type="button"
            className="button-primary"
            onClick={() => handleOpenAdd()}
            style={{ whiteSpace: "nowrap" }}
          >
            + Add Prescription
          </button>
        </div>
        {active.length ? (
          <section className="state-group" aria-label="Daily prescriptions">
            <h3>
              Daily prescriptions <span className="count-badge">{active.length}</span>
            </h3>
            <ul className="list">
              {(expanded ? active : active.slice(0, ACTIVE_LIMIT)).map((med) => (
                <MedicationRow key={med.id} med={med} onSource={onSource} onOpenDocument={onOpenDocument} />
              ))}
            </ul>
            {active.length > ACTIVE_LIMIT ? (
              <button
                type="button"
                className="text-button"
                aria-expanded={expanded}
                onClick={() => setExpanded((value) => !value)}
              >
                {expanded ? "Show fewer" : `Show all ${active.length}`}
              </button>
            ) : null}
          </section>
        ) : null}
        {rest.map(([key, groupTitle]) => (
          <details className="state-group compact-med-group" key={key} open>
            <summary>
              {groupTitle} <span className="count-badge">{timeline[key].length}</span>
            </summary>
            <ul className="list">
              {timeline[key].map((med) => (
                <MedicationRow key={med.id} med={med} onSource={onSource} onOpenDocument={onOpenDocument} />
              ))}
            </ul>
          </details>
        ))}
        {renderAddModal()}
      </Panel>
    );
  }

  const groups = STATES.map(([state, label]) => [
    label,
    medications.filter((item) => (item.state || item.status) === state),
  ]).filter(([, items]) => items.length);

  return (
    <Panel title={panelTitle}>
      <div className="section-head-actions" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "12px" }}>
        <p className="result-note" style={{ margin: 0 }}>Active prescriptions and doctor-ordered regimens.</p>
        <button
          type="button"
          className="button-primary"
          onClick={() => handleOpenAdd()}
          style={{ whiteSpace: "nowrap" }}
        >
          + Add Prescription
        </button>
      </div>

      {!medications.length ? (
        <div className="empty-prescription-box" style={{ padding: "24px", textAlign: "center", border: "1px dashed var(--border-color, #cbd5e1)", borderRadius: "8px" }}>
          <p className="empty">No medications recorded.</p>
          <button type="button" className="button-secondary" onClick={() => handleOpenAdd()} style={{ marginTop: "8px" }}>
            + Record First Prescription
          </button>
        </div>
      ) : (
        groups.map(([label, items]) => (
          <div className="rx-state-group" key={label} style={{ marginTop: "16px" }}>
            <h3 style={{ fontSize: "14px", fontWeight: 600, color: "var(--text-muted, #475569)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: "8px" }}>
              {label} <span className="count-badge">{items.length}</span>
            </h3>
            <div className="table-wrap">
              <table className="rx-table">
                <thead>
                  <tr>
                    <th scope="col">Medicine & Strength</th>
                    <th scope="col">Schedule</th>
                    <th scope="col">Duration</th>
                    <th scope="col">Prescribed By / Date</th>
                    <th scope="col">Status</th>
                    <th scope="col" style={{ textAlign: "right" }}>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((med) => {
                    const isBusy = busyId === med.id;
                    const currentStatus = med.state || med.status || "prescribed";
                    const meta = med.clinical_metadata || {};
                    const prescribedBy = meta.prescribed_by || (med.source_doc_id ? `Source Doc` : "Doctor");
                    const medDate = med.start_date || med.event_date || meta.event_date;
                    const duration = meta.duration || "Ongoing";

                    return (
                      <tr key={med.id} style={{ opacity: isBusy ? 0.6 : 1 }}>
                        <td>
                          <div className="rx-name-cell">
                            <strong>{med.brand_raw}</strong>
                            {med.salt ? <span className="rx-salt"> ({med.salt})</span> : null}
                            {med.dose ? <span className="rx-dose"> · {med.dose}</span> : null}
                          </div>
                          {med.source_doc_id ? (
                            <button
                              type="button"
                              className="text-button item-source"
                              onClick={() => onOpenDocument?.(med.source_doc_id, med.page || 1)}
                              style={{ fontSize: "12px", marginTop: "2px" }}
                            >
                              Source Doc · p.{med.page || 1}
                            </button>
                          ) : null}
                        </td>
                        <td>
                          <ScheduleBadge freq={med.freq} dose={med.dose} />
                        </td>
                        <td>{duration}</td>
                        <td>
                          <div>{prescribedBy}</div>
                          <small style={{ color: "var(--text-muted, #64748b)" }}>{formatDate(medDate)}</small>
                        </td>
                        <td>
                          <div className="rx-status-pills" style={{ display: "flex", gap: "4px" }}>
                            <button
                              type="button"
                              className={`pill ${currentStatus === "prescribed" ? "success" : "ghost"}`}
                              onClick={() => handleStatusToggle(med, "prescribed")}
                              title="Mark Active"
                            >
                              Active
                            </button>
                            <button
                              type="button"
                              className={`pill ${currentStatus === "reported_ongoing" ? "warning" : "ghost"}`}
                              onClick={() => handleStatusToggle(med, "reported_ongoing")}
                              title="Mark SOS / As Needed"
                            >
                              SOS
                            </button>
                            <button
                              type="button"
                              className={`pill ${currentStatus === "reported_stopped" ? "neutral" : "ghost"}`}
                              onClick={() => handleStatusToggle(med, "reported_stopped")}
                              title="Mark Completed"
                            >
                              Completed
                            </button>
                          </div>
                        </td>
                        <td style={{ textAlign: "right" }}>
                          <button
                            type="button"
                            className="text-button"
                            onClick={() => handleOpenAdd(med)}
                            style={{ marginRight: "8px" }}
                          >
                            Edit
                          </button>
                          <button
                            type="button"
                            className="text-button danger"
                            onClick={() => handleDeleteMedication(med.id)}
                          >
                            Delete
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        ))
      )}

      {renderAddModal()}
    </Panel>
  );
}
