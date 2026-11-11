import { http, HttpResponse } from "msw";
import { makeCreateProjectResponse, makeProject } from "../../fixtures/projects";
import { successEnvelope } from "../../fixtures/envelope";
import { api } from "../base";

export const projectHandlers = [
  http.get(api("/projects"), () => HttpResponse.json(successEnvelope([makeProject()]))),
  http.post(api("/projects"), () => HttpResponse.json(successEnvelope(makeCreateProjectResponse()), { status: 201 })),
];
