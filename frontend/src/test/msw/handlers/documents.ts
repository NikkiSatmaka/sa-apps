import { http, HttpResponse } from "msw";
import { makeDocument } from "../../fixtures/documents";
import { successEnvelope } from "../../fixtures/envelope";
import { api } from "../base";

export const documentHandlers = [
  // Backend: { documents: [...], total } di dalam `data`
  http.get(api("/projects/:id/documents"), () =>
    HttpResponse.json(successEnvelope({ documents: [makeDocument()], total: 1 }))
  ),
];
