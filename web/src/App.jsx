import { useEffect, useRef, useState } from "react";
import Auth from "./pages/Auth";
import Dashboard from "./pages/Dashboard";
import DocumentDetail from "./pages/DocumentDetail";
import Intake from "./pages/Intake";
import Queue from "./pages/Queue";
import { requestJson } from "./lib/api";
import { readRoute, routeHash } from "./lib/navigation";

export default function App() {
  const [patient, setPatient] = useState(null);
  const [checking, setChecking] = useState(true);
  const [summaryData, setSummaryData] = useState(null);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [summaryError, setSummaryError] = useState("");
  const [timeline, setTimeline] = useState([]);
  const [timelineLoading, setTimelineLoading] = useState(true);
  const [timelineError, setTimelineError] = useState("");
  const [activeJobs, setActiveJobs] = useState([]);
  const [route, setRoute] = useState(readRoute);
  const { view, documentId, page: documentPage } = route;
  const routeRef = useRef(route);
  const navigationGuard = useRef(null);
  const documentReturn = useRef("summary");
  const [refresh, setRefresh] = useState(0);
  const previousView = useRef(view);
  const previousPatient = useRef(null);

  function navigate(view, documentId = null, page = 1) {
    const next = { view, documentId, page };
    routeRef.current = next;
    setRoute(next);
    window.location.hash = routeHash(next);
  }

  useEffect(() => {
    function changed() {
      const next = readRoute();
      if (routeHash(next) === routeHash(routeRef.current)) return;
      if (navigationGuard.current && !navigationGuard.current()) {
        window.history.replaceState(null, "", routeHash(routeRef.current));
        return;
      }
      routeRef.current = next;
      setRoute(next);
    }
    if (window.location.hash !== routeHash(routeRef.current)) {
      window.history.replaceState(null, "", routeHash(routeRef.current));
    }
    window.addEventListener("hashchange", changed);
    return () => window.removeEventListener("hashchange", changed);
  }, []);

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
          setSummaryData(null);
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
    if (!patient) {
      setTimeline([]);
      setTimelineLoading(false);
      return;
    }
    let cancelled = false;
    setTimelineLoading(true);
    setTimelineError("");
    requestJson(`/api/patients/${patient.id}/timeline`)
      .then((data) => {
        if (!cancelled) setTimeline(data.reports ?? []);
      })
      .catch((err) => {
        if (cancelled) return;
        if (err?.status === 401) {
          setPatient(null);
          setTimeline([]);
          return;
        }
        setTimelineError(
          err instanceof Error ? err.message : "Could not load the timeline.",
        );
      })
      .finally(() => {
        if (!cancelled) setTimelineLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [patient, refresh]);

  useEffect(() => {
    if (!patient || view !== "summary") {
      return undefined;
    }
    let cancelled = false;
    let timer;
    let stopped = false;
    async function poll() {
      try {
        const data = await requestJson("/api/jobs?scope=active&limit=5&offset=0");
        if (!cancelled) setActiveJobs(data.jobs ?? []);
      } catch (err) {
        if (cancelled) return;
        // Keep the last observation on transient errors; stop on a lost session.
        stopped = [401, 403].includes(err?.status);
      } finally {
        if (!cancelled && !stopped) timer = setTimeout(poll, 2000);
      }
    }
    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [patient, view, refresh]);

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
    setSummaryError("");
    setTimeline([]);
    setTimelineError("");
    setActiveJobs([]);
    navigate("summary");
  }

  function handleAuthenticated(data) {
    setPatient(data);
    setSummaryData(null);
    setSummaryLoading(true);
    setSummaryError("");
    setTimeline([]);
    setTimelineError("");
    navigate("summary");
  }

  function handleOpenDocument(id, page = 1) {
    documentReturn.current = view === "queue" ? "queue" : "summary";
    navigate("document", id, page);
  }

  function handleDone() {
    navigate("summary");
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
        key={patient.id}
        patient={patient}
        onDone={handleDone}
        onOpenDocument={handleOpenDocument}
        onSignOut={handleLogout}
        onQueue={() => navigate("queue")}
        navigationGuard={navigationGuard}
      />
    );
  }

  if (view === "document" && documentId) {
    return (
      <DocumentDetail
        documentId={documentId}
        patient={patient}
        initialPage={documentPage}
        onPageChange={(page) => navigate("document", documentId, page)}
        onBack={() => {
          navigate(documentReturn.current);
          setRefresh((value) => value + 1);
        }}
        onSignOut={handleLogout}
        onQueue={() => navigate("queue")}
        backLabel={documentReturn.current === "queue" ? "Back to queue" : "Back to summary"}
        onSummary={setSummaryData}
      />
    );
  }

  if (view === "queue") {
    return <Queue key={patient.id} patient={patient} onDone={handleDone}
      onAdd={() => navigate("intake")} onOpenDocument={handleOpenDocument} onSignOut={handleLogout} />;
  }

  return (
    <Dashboard
      data={summaryData}
      patient={patient}
      onAdd={() => navigate("intake")}
      onQueue={() => navigate("queue")}
      onOpenDocument={handleOpenDocument}
      onSignOut={handleLogout}
      loading={summaryLoading}
      error={summaryError}
      timeline={timeline}
      timelineLoading={timelineLoading}
      timelineError={timelineError}
      activeJobs={activeJobs}
    />
  );
}
