import { describe, expect, it } from "vitest";
import {
  bisaMembuatProyek,
  isAdmin,
  isPrivileged,
  isRequester,
  isRequesterTerbatas,
  labelPeran,
  ROLES,
} from "./roles";

/** Role fungsional tunggal + flag `is_admin` (ADR 0012). */
const aktor = (role: string | null | undefined, is_admin?: boolean | null) => ({ role, is_admin });

describe("ROLES", () => {
  it("memuat empat role fungsional tanpa Admin", () => {
    expect([...ROLES]).toEqual(["Sales", "Product", "SA", "Lead_SA"]);
  });
});

describe("isAdmin", () => {
  it.each([
    [aktor("SA", true), true],
    [aktor("Lead_SA", true), true],
    [aktor("Lead_SA", false), false],
    [aktor("SA"), false],
    [aktor("SA", null), false],
    [null, false],
    [undefined, false],
  ])("%j -> %s", (a, hasil) => {
    expect(isAdmin(a)).toBe(hasil);
  });
});

describe("isPrivileged (Lead_SA atau is_admin)", () => {
  it.each([
    [aktor("Lead_SA", false), true],
    [aktor("SA", true), true],
    [aktor("Sales", true), true],
    [aktor("Product", true), true],
    [aktor("SA", false), false],
    [aktor("Sales", false), false],
    [aktor("Product", false), false],
    [aktor(undefined), false],
    [null, false],
  ])("%j -> %s", (a, hasil) => {
    expect(isPrivileged(a)).toBe(hasil);
  });
});

describe("isRequester (Sales atau Product)", () => {
  it.each([
    ["Sales", true],
    ["Product", true],
    ["SA", false],
    ["Lead_SA", false],
    [undefined, false],
  ])("%s -> %s", (role, hasil) => {
    expect(isRequester(aktor(role))).toBe(hasil);
  });
});

describe("isRequesterTerbatas (requester non-privileged)", () => {
  it.each([
    [aktor("Sales", false), true],
    [aktor("Product", false), true],
    [aktor("Sales", true), false],
    [aktor("Product", true), false],
    [aktor("SA", false), false],
    [aktor("Lead_SA", false), false],
  ])("%j -> %s", (a, hasil) => {
    expect(isRequesterTerbatas(a)).toBe(hasil);
  });
});

describe("bisaMembuatProyek (Sales, Product, Lead_SA, atau is_admin; SA tidak)", () => {
  it.each([
    [aktor("Sales", false), true],
    [aktor("Product", false), true],
    [aktor("Lead_SA", false), true],
    [aktor("SA", true), true],
    [aktor("SA", false), false],
    [aktor(undefined), false],
    [null, false],
  ])("%j -> %s", (a, hasil) => {
    expect(bisaMembuatProyek(a)).toBe(hasil);
  });
});

describe("labelPeran", () => {
  it.each([
    [aktor("Product", false), "Product Manager"],
    [aktor("Product", true), "Product Manager · Admin"],
    [aktor("SA", false), "SA"],
    [aktor("SA", true), "SA · Admin"],
    [aktor("Lead_SA", true), "Lead_SA · Admin"],
    [aktor(undefined), "—"],
    [null, "—"],
  ])("%j -> %s", (a, label) => {
    expect(labelPeran(a)).toBe(label);
  });
});
