import { useEffect, useRef, useState } from "react";
import Dashboard from "./pages/Dashboard";
import Intake from "./pages/Intake";

export default function App() {
  const [view, setView] = useState("summary");
  const previousView = useRef(view);

  useEffect(() => {
    if (previousView.current === view) return;
    previousView.current = view;
    document.querySelector("h1")?.focus();
  }, [view]);

  return view === "intake" ? (
    <Intake onDone={() => setView("summary")} />
  ) : (
    <Dashboard onAdd={() => setView("intake")} />
  );
}
