import { describe, expect, it } from "vitest";
import * as barrel from "./index";
import { useAuthStore } from "./auth";
import { useSidebarStore } from "./sidebar";
import { useToastStore } from "./toast";

describe("store barrel", () => {
  it("mengekspor ketiga store yang sama dengan modul aslinya", () => {
    expect(barrel.useAuthStore).toBe(useAuthStore);
    expect(barrel.useSidebarStore).toBe(useSidebarStore);
    expect(barrel.useToastStore).toBe(useToastStore);
  });
});
