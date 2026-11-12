import { useEffect, useRef, useState } from "react";
import { requestJson } from "../lib/api";

export default function RedactionConsent({ documentId, onResolved, cloudAvailable = false }) {
  const dialog = useRef(null);
  const canvas = useRef(null);
  const start = useRef(null);
  const [preview, setPreview] = useState(null);
  const [index, setIndex] = useState(0);
  const [seen, setSeen] = useState(new Set());
  const [boxes, setBoxes] = useState({});
  const [maskMetadata, setMaskMetadata] = useState({});
  const [tool, setTool] = useState("draw"); // "draw" | "erase"
  const [coordinates, setCoordinates] = useState([0, 0, 100, 100]);
  const [editingIndex, setEditingIndex] = useState(null);
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const page = preview?.pages[index];
  const pageNum = page?.page_num;
  const pageBoxes = pageNum && boxes[pageNum] ? boxes[pageNum] : [];

  useEffect(() => {
    const previous = document.activeElement;
    const element = dialog.current;
    if (typeof element.showModal === "function") element.showModal();
    else element.setAttribute("open", "");
    element.querySelector("[data-autofocus]")?.focus();
    return () => { element.close?.(); previous?.focus?.(); };
  }, []);

  useEffect(() => {
    if (!documentId) return;
    const controller = new AbortController();
    requestJson(`/api/documents/${documentId}/redaction-preview`, { signal: controller.signal })
      .then((data) => {
        setPreview(data);
        const initial = {};
        const metadata = {};
        for (const item of data.pages || []) {
          initial[item.page_num] = (item.masks || []).map(([x, y, w, h]) => [y, x, y + h, x + w]);
          metadata[item.page_num] = item.masks || [];
        }
        setBoxes(initial);
        setMaskMetadata(metadata);
      })
      .catch((err) => { if (!controller.signal.aborted) setError(err.message); });
    return () => controller.abort();
  }, [documentId]);

  function draw(draft) {
    const context = canvas.current?.getContext("2d");
    if (!context) return;
    context.clearRect(0, 0, 1000, 1000);
    if (draft) {
      const [y0, x0, y1, x1] = draft;
      context.fillStyle = "rgb(255 196 0 / 32%)";
      context.strokeStyle = "#8a5a00";
      context.lineWidth = 3;
      context.fillRect(x0, y0, x1 - x0, y1 - y0);
      context.strokeRect(x0, y0, x1 - x0, y1 - y0);
    }
  }

  useEffect(() => { draw(); }, [pageNum, boxes]);

  function position(event) {
    const rect = canvas.current.getBoundingClientRect();
    return [
      Math.round(Math.max(0, Math.min(1000, ((event.clientY - rect.top) / rect.height) * 1000))),
      Math.round(Math.max(0, Math.min(1000, ((event.clientX - rect.left) / rect.width) * 1000))),
    ];
  }

  function dragged(event) {
    const [y, x] = position(event);
    return [
      Math.min(start.current[0], y),
      Math.min(start.current[1], x),
      Math.max(start.current[0], y),
      Math.max(start.current[1], x),
    ];
  }

  function addBox(box) {
    const rounded = box.map((v) => Math.round(Number(v)));
    if (rounded.some((v) => !Number.isInteger(v) || v < 0 || v > 1000) || rounded[0] >= rounded[2] || rounded[1] >= rounded[3]) {
      setError("Use coordinates from 0 to 1000, with bottom below top and right beyond left.");
      return;
    }
    if (!pageNum) return;

    setBoxes((current) => {
      const list = current[pageNum] ? [...current[pageNum]] : [];
      if (editingIndex !== null && editingIndex >= 0 && editingIndex < list.length) {
        list[editingIndex] = rounded;
      } else {
        list.push(rounded);
      }
      return { ...current, [pageNum]: list };
    });
    if (editingIndex === null) {
      setMaskMetadata((current) => ({ ...current, [pageNum]: [...(current[pageNum] || []), [0, 0, 1, 1, "custom", crypto.randomUUID()]] }));
    }
    setEditingIndex(null);
    setReviewed(false);
    setError("");
  }

  function eraseBox(boxIndex) {
    if (!pageNum) return;
    setBoxes((current) => {
      const list = current[pageNum] ? [...current[pageNum]] : [];
      if (boxIndex >= 0 && boxIndex < list.length) {
        list.splice(boxIndex, 1);
      }
      const next = { ...current };
      if (list.length > 0) {
        next[pageNum] = list;
      } else {
        delete next[pageNum];
      }
      return next;
    });
    setMaskMetadata((current) => {
      const list = [...(current[pageNum] || [])];
      list.splice(boxIndex, 1);
      return { ...current, [pageNum]: list };
    });
    if (editingIndex === boxIndex) {
      setEditingIndex(null);
    }
    setReviewed(false);
  }

  function clearAllPageBoxes() {
    if (!pageNum) return;
    setBoxes((current) => {
      const next = { ...current };
      delete next[pageNum];
      return next;
    });
    setMaskMetadata((current) => {
      const next = { ...current };
      delete next[pageNum];
      return next;
    });
    setEditingIndex(null);
    setReviewed(false);
  }

  function handlePointerDown(event) {
    const pos = position(event);
    if (tool === "erase") {
      // Find top-most box hit by pointer
      const [y, x] = pos;
      let hit = -1;
      for (let i = pageBoxes.length - 1; i >= 0; i--) {
        const [y0, x0, y1, x1] = pageBoxes[i];
        if (y >= y0 && y <= y1 && x >= x0 && x <= x1) {
          hit = i;
          break;
        }
      }
      if (hit !== -1) {
        eraseBox(hit);
      }
      return;
    }
    start.current = pos;
    canvas.current.setPointerCapture?.(event.pointerId);
  }

  function handlePointerMove(event) {
    if (tool === "draw" && start.current) {
      draw(dragged(event));
    }
  }

  function handlePointerUp(event) {
    if (tool === "draw" && start.current) {
      const box = dragged(event);
      start.current = null;
      // Only record boxes with discernible area (at least 4px width and height) to avoid zero-area clicks
      if (box[2] - box[0] >= 4 && box[3] - box[1] >= 4) {
        addBox(box);
      } else {
        draw();
      }
    }
  }

  async function navigate(direction) {
    if (index + direction >= 0 && index + direction < preview.pages.length) {
      setIndex(index + direction);
      setEditingIndex(null);
      return;
    }
    setBusy(true);
    try {
      const next = await requestJson(`/api/documents/${documentId}/redaction-preview?offset=${preview.offset + direction * 20}`);
      setPreview(next);
      const initial = {};
      const metadata = {};
      for (const item of next.pages || []) {
        initial[item.page_num] = (item.masks || []).map(([x, y, w, h]) => [y, x, y + h, x + w]);
        metadata[item.page_num] = item.masks || [];
      }
      setBoxes((current) => ({ ...initial, ...current }));
      setMaskMetadata((current) => ({ ...metadata, ...current }));
      setIndex(direction > 0 ? 0 : next.pages.length - 1);
      setEditingIndex(null);
      setError("");
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function resolve(approved) {
    if (busy) return;
    setBusy(true);
    try {
      const cleanBoxes = {};
      if (approved && boxes) {
        for (const [k, list] of Object.entries(boxes)) {
          if (Array.isArray(list)) {
            cleanBoxes[String(k)] = list.map((b, i) => {
              const meta = (maskMetadata[k] || [])[i];
              return [Math.round(b[1]), Math.round(b[0]), Math.round(b[3] - b[1]), Math.round(b[2] - b[0]),
                meta?.[4] || "custom", meta?.[5] || crypto.randomUUID()];
            });
          }
        }
      }
      await requestJson(`/api/documents/${documentId}/consent`, {
        method: "POST",
        body: JSON.stringify({ approved, extra_redaction_boxes: cleanBoxes }),
      });
      onResolved();
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  function startEdit(boxIdx, boxCoords) {
    setEditingIndex(boxIdx);
    setCoordinates([...boxCoords]);
  }

  return (
    <dialog
      ref={dialog}
      className="redaction-dialog"
      aria-labelledby="redaction-title"
      onCancel={(event) => {
        event.preventDefault();
        resolve(false);
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          resolve(false);
        }
      }}
    >
      <h2 id="redaction-title">Review masks before cloud analysis</h2>
      <p>
        The source stays local while you review. Only approved masked images are sent. Check every page and remove false positives or add missed identifiers.
      </p>

      {error ? <p className="alert" role="alert">{error}</p> : null}
      {!preview ? <p role="status">Loading pages…</p> : null}

      {page ? (
        <>
          <p>
            Page {page.page_num} · {seen.size} of {preview.total} pages reviewed
          </p>

          <div className="redaction-toolbar">
            <div className="button-group" role="group" aria-label="Redaction tool">
              <button
                type="button"
                className={`button-secondary ${tool === "draw" ? "active" : ""}`}
                aria-pressed={tool === "draw"}
                onClick={() => setTool("draw")}
              >
                Draw mask
              </button>
              <button
                type="button"
                className={`button-secondary ${tool === "erase" ? "active" : ""}`}
                aria-pressed={tool === "erase"}
                onClick={() => setTool("erase")}
              >
                Eraser
              </button>
            </div>
            <div className="button-group">
              <button
                type="button"
                className="text-button"
                disabled={!pageBoxes.length || busy}
                onClick={() => eraseBox(pageBoxes.length - 1)}
              >
                Undo mask
              </button>
              <button
                type="button"
                className="text-button"
                disabled={!pageBoxes.length || busy}
                onClick={clearAllPageBoxes}
              >
                Clear all masks
              </button>
            </div>
          </div>

          <div className="redaction-canvas">
            <img
              src={`data:image/jpeg;base64,${page.jpeg_base64}`}
              alt={`Source page ${page.page_num} for mask review`}
              onLoad={() => setSeen((current) => new Set([...current, page.page_num]))}
              onError={() => {
                setError("This preview could not load. Keep this document offline or try again.");
                setSeen((current) => {
                  const next = new Set(current);
                  next.delete(page.page_num);
                  return next;
                });
              }}
            />
            {pageBoxes.map((box, i) => {
              const [y0, x0, y1, x1] = box;
              const meta = (maskMetadata[pageNum] || [])[i];
              return <div key={meta?.[5] || i} className="redaction-mask" style={{ left: `${x0 / 10}%`, top: `${y0 / 10}%`, width: `${(x1 - x0) / 10}%`, height: `${(y1 - y0) / 10}%` }}>
                <span>{meta?.[4] || "Review mask"}</span>
                <button type="button" aria-label={`Remove ${meta?.[4] || "mask"}`} onPointerDown={(event) => event.stopPropagation()} onClick={() => eraseBox(i)}>×</button>
              </div>;
            })}
            <canvas
              ref={canvas}
              width={1000}
              height={1000}
              aria-hidden="true"
              className={tool === "erase" ? "erase-mode" : ""}
              onPointerDown={handlePointerDown}
              onPointerMove={handlePointerMove}
              onPointerUp={handlePointerUp}
              onPointerCancel={() => {
                start.current = null;
                draw();
              }}
            />
          </div>

          {pageBoxes.length > 0 ? (
            <div className="redaction-mask-list" role="region" aria-label="Current page masks">
              <strong>User masks on page {page.page_num} ({pageBoxes.length}):</strong>
              <ul>
                {pageBoxes.map((b, i) => (
                  <li key={i}>
                    <span>
                      Mask #{i + 1}: <span className="mono">[{b[0]}, {b[1]}] to [{b[2]}, {b[3]}]</span>
                    </span>
                    <div className="button-group">
                      <button
                        type="button"
                        className="text-button"
                        onClick={() => startEdit(i, b)}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        className="text-button"
                        onClick={() => eraseBox(i)}
                      >
                        Remove
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="form-actions">
            <button
              type="button"
              className="button-secondary"
              disabled={busy || (index === 0 && preview.offset === 0)}
              onClick={() => navigate(-1)}
            >
              Previous page
            </button>
            <button
              type="button"
              className="button-secondary"
              disabled={busy || (index === preview.pages.length - 1 && !preview.has_more)}
              onClick={() => navigate(1)}
            >
              Next page
            </button>
          </div>

          <details open={editingIndex !== null}>
            <summary>Add a mask with the keyboard</summary>
            <p>Coordinates run from 0 to 1000 across the full page.</p>
            <div className="redaction-coordinates">
              {["Top", "Left", "Bottom", "Right"].map((label, i) => (
                <label key={label}>
                  {label}
                  <input
                    type="number"
                    min={0}
                    max={1000}
                    step={1}
                    value={coordinates[i]}
                    onChange={(event) =>
                      setCoordinates(
                        coordinates.map((v, j) => (j === i ? Number(event.target.value) : v))
                      )
                    }
                  />
                </label>
              ))}
            </div>
            <div className="form-actions" style={{ marginTop: "8px" }}>
              <button
                type="button"
                className="button-secondary"
                disabled={busy}
                onClick={() => addBox(coordinates)}
              >
                {editingIndex !== null ? "Update mask" : "Add mask"}
              </button>
              {editingIndex !== null ? (
                <button
                  type="button"
                  className="text-button"
                  onClick={() => {
                    setEditingIndex(null);
                    setCoordinates([0, 0, 100, 100]);
                  }}
                >
                  Cancel edit
                </button>
              ) : null}
            </div>
          </details>

          <label className="checkbox-field">
            <input
              type="checkbox"
              checked={reviewed}
              disabled={seen.size < preview.total || busy}
              onChange={(event) => setReviewed(event.target.checked)}
            />
            I reviewed every page and covered identifying information.
          </label>
        </>
      ) : null}

      <div className="form-actions">
        <button
          type="button"
          className="button-secondary"
          disabled={busy}
          data-autofocus
          onClick={() => resolve(false)}
        >
          Keep 100% Offline
        </button>
        {cloudAvailable ? <button
          type="button"
          className="button-primary"
          disabled={busy || !reviewed || !preview || seen.size < preview.total}
          onClick={() => resolve(true)}
        >
          Approve &amp; Send Masked Pages
        </button> : null}
      </div>
    </dialog>
  );
}
