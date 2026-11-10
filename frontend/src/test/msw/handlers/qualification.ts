import { http, HttpResponse } from "msw";
import { successEnvelope } from "../../fixtures/envelope";
import { makeQualificationSchema } from "../../fixtures/qualification";
import { api } from "../base";

export const qualificationHandlers = [
  http.get(api("/qualification/schema"), () => HttpResponse.json(successEnvelope(makeQualificationSchema()))),
];
