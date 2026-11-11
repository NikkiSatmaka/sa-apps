import { http, HttpResponse } from "msw";
import { successEnvelope } from "../../fixtures/envelope";
import { makePaginatedNotifications } from "../../fixtures/notifications";
import { api } from "../base";

export const notificationHandlers = [
  http.get(api("/notifications"), () => HttpResponse.json(successEnvelope(makePaginatedNotifications()))),
  http.get(api("/notifications/unread-count"), () => HttpResponse.json(successEnvelope({ count: 1 }))),
  http.patch(api("/notifications/:id/read"), () => HttpResponse.json(successEnvelope(null))),
];
