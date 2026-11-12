export default function PageOverlay({ src, alt, boxes = [], activeBox = null }) {
  const visible = boxes.filter((box) => Array.isArray(box) && box.length === 4);

  return (
    <div className="page-overlay" role="img" aria-label={alt}>
      <img src={src} alt="" />
      {visible.map(([x0, y0, x1, y1], index) => {
        const isActive =
          activeBox &&
          Math.abs(activeBox[0] - x0) < 0.001 &&
          Math.abs(activeBox[1] - y0) < 0.001 &&
          Math.abs(activeBox[2] - x1) < 0.001 &&
          Math.abs(activeBox[3] - y1) < 0.001;

        return (
          <span
            key={`${x0}-${y0}-${index}`}
            className={isActive ? "page-overlay-box active" : "page-overlay-box"}
            style={{
              left: `${x0 * 100}%`,
              top: `${y0 * 100}%`,
              width: `${(x1 - x0) * 100}%`,
              height: `${(y1 - y0) * 100}%`,
            }}
          />
        );
      })}
    </div>
  );
}
