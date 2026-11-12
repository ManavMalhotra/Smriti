export function clinicalSource(item, anchor = item) {
  const page = anchor.page_num ?? item.page_num ?? item.page ?? 1;
  const doc = item.doc_id ?? item.source_doc_id ?? item.document_id;
  const box = anchor.bbox_2d ?? item.bbox_2d;
  const bbox = box ? [box[1] / 1000, box[0] / 1000, box[3] / 1000, box[2] / 1000] : item.bbox;
  return { page, document_id: doc, bbox, analyte: item.title, date: item.event_date,
    pageUrl: `/api/documents/${doc}/page/${page}` };
}

export default function SourcePills({ item, onSource }) {
  if (!(item.doc_id ?? item.source_doc_id ?? item.document_id)) return null;
  const anchors = item.source_anchors?.length ? item.source_anchors : [item];
  return anchors.map((anchor, index) => (
    <button type="button" className="text-button source-pill" key={index}
      aria-label={`Open source for ${item.title ?? item.brand_raw ?? "finding"} on page ${anchor.page_num ?? item.page_num ?? item.page ?? 1}`}
      onClick={() => onSource?.(clinicalSource(item, anchor))}>
      [p.{anchor.page_num ?? item.page_num ?? item.page ?? 1}]
    </button>
  ));
}
