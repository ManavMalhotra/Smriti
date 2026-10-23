import { useState } from "react";
import Dashboard from "./pages/Dashboard";
import Intake from "./pages/Intake";

export default function App() {
  const [view, setView] = useState("summary");

  return view === "intake" ? (
    <Intake onDone={() => setView("summary")} />
  ) : (
    <Dashboard onAdd={() => setView("intake")} />
  );
}
