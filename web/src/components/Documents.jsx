import Panel from "./Panel";
import { docTypeLabel, formatDate, statusLabel } from "../lib/format";

export default function Documents({ documents = [] }) {
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
              </tr>
            </thead>
            <tbody>
              {documents.map((document) => (
                <tr key={document.id}>
                  <td>
                    <span className="doc-type">{docTypeLabel(document.doc_type)}</span>
                    <span className="doc-id">{document.id}</span>
                  </td>
                  <td>{formatDate(document.doc_date ?? document.collection_date)}</td>
                  <td>{document.page_count}</td>
                  <td>{statusLabel(document.status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
