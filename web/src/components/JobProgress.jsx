import { useEffect, useState } from "react";

const STAGES = ["Read", "Extract", "Verify", "Save"];
const STAGE_INDEX = { ocr_loading: 0, ocr: 0, classification: 1, extraction: 1, qwen_loading: 2, qwen: 2, cleanup: 2, cross_check: 2, saving: 3, done: 4 };
const LEVELS = { info: "Activity", success: "Complete", warning: "Warning", error: "Error" };
const COUNT_UNITS = { page_read: "words", qwen_page: "fields", handwriting_filtered: "fields excluded", cross_checked: "fields compared", saving: "fields", done: "fields saved" };

function elapsedLabel(seconds) {
  const value = Math.max(0, Math.floor(seconds));
  if (value < 60) return `${value}s`;
  if (value < 3600) return `${Math.floor(value / 60)}m ${value % 60}s`;
  return `${Math.floor(value / 3600)}h ${Math.floor(value / 60) % 60}m`;
}

function modelLabel(model) {
  if (model?.startsWith("vlm:glm-ocr")) return "GLM-OCR 0.9B";
  if (model?.startsWith("vlm:qwen3-vl")) return "Qwen3-VL 4B";
  if (model?.startsWith("rapidocr:")) return "RapidOCR";
  if (model?.startsWith("paddle:")) return "PaddleOCR";
  if (model?.startsWith("pymupdf:")) return "PDF text layer";
  return model;
}

export default function JobProgress({ job, compact = false, detailsOpen = false }) {
  const [now, setNow] = useState(Date.now);
  const terminal = job?.state === "done" || job?.state === "failed";
  const started = Date.parse(job?.started_at);
  const finished = Date.parse(job?.finished_at);
  const events = job?.events ?? [];
  const latest = events.at(-1);
  const context = job?.state === "failed" ? job.failure_context ?? job : job;
  const stageIndex = STAGE_INDEX[context?.stage];
  const attemptStart = events.findLastIndex((event) => ["started", "recovered"].includes(event.event));
  const attemptEvents = events.slice(attemptStart + 1);
  const verification = job?.verification_state ?? (attemptEvents.some((event) => ["qwen_disabled", "handwritten_mode"].includes(event.event)) ? "skipped" : null);
  const elapsed = job?.elapsed_seconds ?? (Number.isFinite(started) && (!terminal || Number.isFinite(finished)) ? ((terminal ? finished : now) - started) / 1000 : null);

  useEffect(() => {
    if (!Number.isFinite(started) || terminal || job?.state !== "running") return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [started, terminal, job?.state]);

  const activity = latest?.message ?? job?.activity ?? ({ queued: "Waiting for the local worker", running: "Processing locally", done: "Results saved; ready to review", failed: "Local processing failed" }[job?.state] ?? "Waiting for processing updates");
  const knownProgress = job?.stage_total > 0 && job?.completed_pages != null && ["ocr", "qwen"].includes(job?.stage);

  return (
    <div className="job-progress" data-state={job?.state ?? "queued"}>
      <div className="job-activity" role="status"><span className="activity-dot" aria-hidden="true" />{activity}</div>
      <div className="job-current">
        {context?.model ? <span title={context.model}>{modelLabel(context.model)}</span> : null}
        {context?.current_page ? <span>{["qwen", "qwen_loading"].includes(context.stage) ? "Source page" : "Page"} {context.current_page}{job.total ? ` of ${job.total}` : ""}</span> : null}
        {elapsed != null ? <span className="job-elapsed" aria-label={`Elapsed ${elapsedLabel(elapsed)}`}>{elapsedLabel(elapsed)}</span> : null}
        {context?.code ? <code>{context.code}</code> : null}
        {context?.status ? <span>HTTP {context.status}</span> : null}
      </div>
      {!terminal && knownProgress ? (
        <div className="job-meter">
          <progress aria-label={job?.stage === "qwen" ? "Qwen3-VL page reading" : job?.stage === "ocr" ? "OCR page reading" : "Local processing"} max={job.stage_total} value={job.completed_pages} />
          <span>{job.completed_pages} / {job.stage_total} {job.stage === "qwen" ? `eligible pages ${verification === "partial" ? "resolved" : "read"}` : "pages read"}</span>
        </div>
      ) : null}
      {!compact && stageIndex != null ? (
        <ol className="job-stages" aria-label="Processing stages">
          {STAGES.map((label, index) => {
            let state = stageIndex > index ? "complete" : stageIndex === index ? job?.state === "failed" ? "failed" : "active" : job?.state === "failed" ? "not_reached" : "waiting";
            if (index === 2 && verification === "skipped") state = "skipped";
             if (index === 2 && stageIndex > index && verification !== "compared" && verification !== "skipped") state = ["partial", "unavailable"].includes(verification) ? verification : "unknown";
             return <li key={label} data-state={state}><span>{label}</span><small>{{ skipped: "Skipped", partial: "Partial; review required", unavailable: "OCR-only; review required", unknown: "Unverified", complete: "Finished", active: "Active", failed: "Failed", waiting: "Waiting", not_reached: "Not reached" }[state]}</small></li>;
          })}
        </ol>
      ) : null}
      {!compact ? <details className="job-log" open={detailsOpen || undefined}>
        <summary>Processing details</summary>
        {job?.support_id || job?.id ? <p className="job-id mono">Support ID {job.support_id ?? job.id}</p> : null}
        {job?.logging && ["file", "terminal"].some((name) => !job.logging[name]?.available || job.logging[name]?.degraded) ? (
          <p className="job-log-warning">Local diagnostic logging is degraded. Processing updates below remain available; some file or terminal events may be missing.</p>
        ) : null}
        {job?.latest_failure && !events.some((event) => event.sequence === job.latest_failure.sequence) ? <p className="job-log-warning">Latest failure: {job.latest_failure.message}</p> : null}
        {job?.events_truncated > 0 ? <p className="job-log-warning">{job.events_truncated} earlier events omitted; showing the latest {events.length}.</p> : null}
        {events.length ? (
          <ol className="job-events">
            {[...events].reverse().map((event) => (
              <li key={event.sequence} data-level={event.level}>
                <div className="job-event-head">
                  <span className="event-level">{LEVELS[event.level] ?? event.level}</span>
                  <time dateTime={event.timestamp} title={event.timestamp}>{new Date(event.timestamp).toLocaleTimeString([], { hour12: false })}</time>
                </div>
                <p>{event.message}</p>
                <div className="job-event-meta">
                  {event.page ? <span>Page {event.page}</span> : null}
                  {event.count != null ? <span>{event.count} {COUNT_UNITS[event.event] ?? "items"}</span> : null}
                  {event.duration_seconds != null ? <span>{event.duration_seconds.toFixed(2)}s</span> : null}
                  {event.error_type ? <code>{event.error_type}</code> : null}
                  {event.code ? <code>{event.code}</code> : null}
                  {event.status ? <span>HTTP {event.status}</span> : null}
                  {event.model ? <code>{event.model}</code> : null}
                </div>
              </li>
            ))}
          </ol>
        ) : <p className="result-note">Detailed history is unavailable for this job.</p>}
      </details> : null}
    </div>
  );
}
