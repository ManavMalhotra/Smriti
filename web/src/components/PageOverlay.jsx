export default function PageOverlay({ src, alt, boxes = [] }) {
  const visible = boxes.filter((box) => Array.isArray(box) && box.length === 4);

  return (
    <div className="page-overlay" role="img" aria-label={alt}>
      <img src={src} alt="" />
      {visible.map(([x0, y0, x1, y1], index) => (
        <span
          key={`${x0}-${y0}-${index}`}
          className="page-overlay-box"
          style={{
            left: `${x0 * 100}%`,
            top: `${y0 * 100}%`,
            width: `${(x1 - x0) * 100}%`,
            height: `${(y1 - y0) * 100}%`,
          }}
        />
      ))}
    </div>
  );
}
