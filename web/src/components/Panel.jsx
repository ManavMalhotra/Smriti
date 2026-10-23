function slug(title) {
  return title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/(^-|-$)/g, "");
}

export default function Panel({ title, id, children }) {
  const headingId = id ?? `${slug(title)}-heading`;

  return (
    <section className="panel" aria-labelledby={headingId}>
      <h2 id={headingId}>{title}</h2>
      {children}
    </section>
  );
}
