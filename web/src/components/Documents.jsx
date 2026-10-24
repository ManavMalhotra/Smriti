import Panel from "./Panel";
import { docTypeLabel, formatDate, statusLabel } from "../lib/format";

export default function Documents({ documents = [], onOpen }) {
  return (
    <Panel title="Documents">
      {documents.length === 0 ? (
        <p className="empty">No source documents.</p>
      ) : (
        <div className="table-wrap">
          <table>
            <caption className="sr-only">Source documents</caption>
            <thead>
              <tr>
                <th scope="col">Document</th>
                <th scope="col">Date</th>
                <th scope="col">Pages</th>
                <th scope="col">Status</th>
                {onOpen ? <th scope="col">Review</th> : null}
              </tr>
            </thead>
            <tbody>
              {documents.map((document) => {
                const reviewCount = document.review_count ?? 0;
                return (
                  <tr key={document.id}>
                    <td>
                      <span className="doc-type">{docTypeLabel(document.doc_type)}</span>
                      <span className="doc-id">{document.id}</span>
                    </td>
                    <td>{formatDate(document.doc_date ?? document.collection_date)}</td>
                    <td>{document.page_count}</td>
                    <td>
                      <span>{statusLabel(document.status)}</span>
                      {reviewCount > 0 ? (
                        <span className="doc-review">
                          {reviewCount} {reviewCount === 1 ? "field" : "fields"} to review
                        </span>
                      ) : null}
                    </td>
                    {onOpen ? (
                      <td>
                        <button
                          type="button"
                          className="text-button"
                          onClick={() => onOpen(document.id)}
                          aria-label={`Review ${docTypeLabel(document.doc_type)} ${document.id}`}
                        >
                          Open
                        </button>
                      </td>
                    ) : null}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
