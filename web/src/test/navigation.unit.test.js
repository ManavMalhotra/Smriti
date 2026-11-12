import { afterEach, describe, expect, it } from "vitest";
import { readRoute, routeHash } from "../lib/navigation";

afterEach(() => window.history.replaceState(null, "", "/"));

describe("hash routes", () => {
  it.each(["summary", "intake", "queue"])("round-trips %s", (view) => {
    window.history.replaceState(null, "", `#/${view}`);
    expect(readRoute().view).toBe(view);
    expect(routeHash(readRoute())).toBe(`#/${view}`);
  });

  it("preserves a document source page and rejects invalid routes and page numbers", () => {
    window.history.replaceState(null, "", "#/documents/d-01?page=21");
    expect(readRoute()).toEqual({ view: "document", documentId: "d-01", page: 21 });
    expect(routeHash(readRoute())).toBe("#/documents/d-01?page=21");
    for (const page of ["0", "-1", "NaN", "1.5", "999999999999999999999"]) {
      window.history.replaceState(null, "", `#/documents/d-01?page=${page}`);
      expect(readRoute().page).toBe(1);
    }
    window.history.replaceState(null, "", "#/documents/../../private");
    expect(readRoute().view).toBe("summary");
  });
});
