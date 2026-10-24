import { useEffect, useRef, useState } from "react";
import Auth from "./pages/Auth";
import Dashboard from "./pages/Dashboard";
import DocumentDetail from "./pages/DocumentDetail";
import Intake from "./pages/Intake";
import { requestJson } from "./lib/api";

export default function App() {
  const [patient, setPatient] = useState(null);
  const [checking, setChecking] = useState(true);
  const [summaryData, setSummaryData] = useState(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState("");
  const [view, setView] = useState("summary");
  const [documentId, setDocumentId] = useState(null);
  const [refresh, setRefresh] = useState(0);
  const previousView = useRef(view);
  const previousPatient = useRef(null);

  useEffect(() => {
    let cancelled = false;
    requestJson("/api/auth/me")
      .then((data) => {
        if (!cancelled) setPatient(data);
      })
      .catch(() => {
        // A missing or expired session is expected on first load.
      })
      .finally(() => {
        if (!cancelled) setChecking(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!patient) {
      setSummaryData(null);
      return;
    }
    let cancelled = false;
    setSummaryLoading(true);
    setSummaryError("");
    requestJson(`/api/patients/${patient.id}/summary`)
      .then((data) => {
        if (!cancelled) setSummaryData(data);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err?.status === 401) {
          setPatient(null);
          return;
        }
        setSummaryError(err instanceof Error ? err.message : "Could not load the summary.");
      })
      .finally(() => {
        if (!cancelled) setSummaryLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [patient, refresh]);

  useEffect(() => {
    if (previousView.current === view) return;
    previousView.current = view;
    document.querySelector("h1")?.focus();
  }, [view]);

  useEffect(() => {
    const next = patient?.id ?? null;
    if (previousPatient.current === next) return;
    previousPatient.current = next;
    if (next) document.querySelector("h1")?.focus();
  }, [patient]);

  async function handleLogout() {
    try {
      await requestJson("/api/auth/logout", { method: "POST" });
    } catch {
      // The local session is cleared even if the server is already unavailable.
    }
    setPatient(null);
    setSummaryData(null);
    setDocumentId(null);
    setView("summary");
  }

  function handleAuthenticated(data) {
    setPatient(data);
    setDocumentId(null);
    setView("summary");
  }

  function handleOpenDocument(id) {
    setDocumentId(id);
    setView("document");
  }

  function handleDone() {
    setDocumentId(null);
    setView("summary");
    setRefresh((value) => value + 1);
  }

  if (checking) {
    return (
      <div className="shell auth-shell">
        <main className="auth-main">
          <p className="empty" role="status">
            Loading…
          </p>
        </main>
      </div>
    );
  }

  if (!patient) {
    return <Auth onAuthenticated={handleAuthenticated} />;
  }

  if (view === "intake") {
    return (
      <Intake
        patient={patient}
        onDone={handleDone}
        onOpenDocument={handleOpenDocument}
        onSignOut={handleLogout}
      />
    );
  }

  if (view === "document" && documentId) {
    return (
      <DocumentDetail
        documentId={documentId}
        patient={patient}
        onBack={handleDone}
        onSignOut={handleLogout}
        onSummary={setSummaryData}
      />
    );
  }

  return (
    <Dashboard
      data={summaryData}
      patient={patient}
      onAdd={() => setView("intake")}
      onOpenDocument={handleOpenDocument}
      onSignOut={handleLogout}
      loading={summaryLoading}
      error={summaryError}
    />
  );
}
