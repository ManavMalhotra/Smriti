export function readRoute() {
  const [path, query = ""] = window.location.hash.slice(1).split("?");
  if (["/summary", "/documents", "/intake", "/queue"].includes(path)) {
    return { view: path.slice(1), documentId: null, page: 1 };
  }
  const document = /^\/documents\/([A-Za-z0-9_-]{1,64})$/.exec(path);
  if (document) {
    const page = Number(new URLSearchParams(query).get("page") ?? 1);
    return { view: "document", documentId: document[1], page: Number.isSafeInteger(page) && page > 0 ? page : 1 };
  }
  return { view: "summary", documentId: null, page: 1 };
}

export function routeHash(route) {
  if (route.view !== "document") return `#/${route.view}`;
  return `#/documents/${route.documentId}${route.page > 1 ? `?page=${route.page}` : ""}`;
}
