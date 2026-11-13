const dateFormatter = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

export function formatDate(value) {
  if (!value) return "—";
  const date = value.length === 10 ? `${value}T00:00:00Z` : value;
  return dateFormatter.format(new Date(date));
}

export function shortId(value) {
  if (!value) return "—";
  return value.length > 12 ? `${value.slice(0, 8)}…` : value;
}

export function formatSex(sex) {
  return { F: "Female", M: "Male", O: "Other" }[sex] ?? "Sex not recorded";
}

export function formatRange(low, high) {
  if (low != null && high != null) return `${low}–${high}`;
  if (low != null) return `≥ ${low}`;
  if (high != null) return `≤ ${high}`;
  return "—";
}

export function docTypeLabel(type) {
  return (
    {
      lab_report: "Lab report",
      prescription: "Prescription",
      pharmacy: "Pharmacy slip",
      discharge_summary: "Discharge summary",
      ct: "CT report",
      mri: "MRI report",
      xray: "X-ray report",
      pathology: "Pathology report",
      radiology: "Imaging report",
      other: "Document",
    }[type] ?? type
  );
}

export const reportCategories = [
  "lab",
  "imaging",
  "prescription",
  "discharge",
  "pathology",
  "other",
];

export function categoryLabel(category) {
  return (
    {
      lab: "Lab",
      imaging: "Imaging",
      prescription: "Prescription",
      discharge: "Discharge",
      pathology: "Pathology",
      other: "Other",
    }[category] ?? category
  );
}

export function statusLabel(status) {
  return (
    {
      queued: "Queued",
      processing: "Processing",
      awaiting_cloud_consent: "Review redaction",
      done: "Processed",
      failed: "Failed",
      rejected_quality: "Rejected",
      review: "Review",
      auto: "Accepted",
      rejected: "Rejected",
    }[status] ?? status
  );
}

export function actionLabel(action) {
  return (
    {
      review: "Review",
      test: "Test",
      appointment: "Appointment",
      other: "Action",
    }[action] ?? action
  );
}

export function anchorLabel(anchor) {
  return (
    {
      collection_date: "collection date",
      doc_date: "document date",
      unknown: "unknown date",
    }[anchor] ?? anchor
  );
}

export function stateLabel(state) {
  return (
    {
      open: "Open",
      done: "Done",
      superseded: "Superseded",
      unknown_date: "Date unknown",
    }[state] ?? state
  );
}

export function engineTrustBadge(engine, status, isHumanReviewed = false) {
  if (engine === "human" || isHumanReviewed || status === "accepted" || status === "auto") {
    if (engine === "human" || isHumanReviewed) {
      return { label: "Human Verified", className: "trust-human" };
    }
  }
  const e = (engine || "").toLowerCase();
  if (e === "human") {
    return { label: "Human Verified", className: "trust-human" };
  }
  if (e.includes("gemini") || e.includes("cloud")) {
    return { label: "Gemini (Cloud Encrypted)", className: "trust-gemini" };
  }
  if (e.includes("vlm") || e.includes("llama") || e.includes("qwen")) {
    return { label: "llama-server (Local GPU)", className: "trust-vlm" };
  }
  return { label: "RapidOCR (Local)", className: "trust-ocr" };
}

