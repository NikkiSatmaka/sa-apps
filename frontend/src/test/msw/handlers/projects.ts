import { http, HttpResponse } from "msw";
import { makeCreateProjectResponse, makeProject } from "../../fixtures/projects";
import { successEnvelope } from "../../fixtures/envelope";
import { api } from "../base";

export const projectHandlers = [
  http.get(api("/projects"), ({ request }) => {
    const params = new URL(request.url).searchParams;
    const page = Number(params.get("page") ?? "1");
    const pageSize = Number(params.get("page_size") ?? "20");
    const items = [makeProject()];
    return HttpResponse.json(successEnvelope({
      items: items.slice((page - 1) * pageSize, page * pageSize),
      total: items.length,
      page,
      page_size: pageSize,
      total_pages: Math.ceil(items.length / pageSize),
    }));
  }),
  http.post(api("/projects"), () => HttpResponse.json(successEnvelope(makeCreateProjectResponse()), { status: 201 })),
];
