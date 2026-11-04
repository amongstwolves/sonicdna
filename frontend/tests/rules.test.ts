/** The UI wording rules, checked against the source so a later edit can't slip past them. */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = join(__dirname, "..");

function sources(directory: string): string[] {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(name) ? [path] : [];
  });
}

const files = ["app", "components", "lib"].flatMap((dir) => sources(join(ROOT, dir)));

describe("UI wording rules", () => {
  it("finds the source files", () => {
    expect(files.length).toBeGreaterThan(10);
  });

  it.each([
    ["accuracy", /accura(te|cy)/i],
    ["percent match", /percent/i],
    ["% identical", /identical/i],
    ["the log's score field", /\bscore\b/i],
    ["a percent sign after a number or value", /(\d|\}|toFixed\([^)]*\))\s*%/],
    ["a percent string", /["'`]\s*%/],
    ["the old Alchemy stub", /not yet connected|screen preview|not connected/i],
    ["held-out targets being closed", /aren.t analysed|isn.t analysed|can.t be analysed|play only/i],
    ["the old upload wording", /nothing is sent to a model/i],
  ])("source never mentions %s", (_name, pattern) => {
    const hits = files.filter((file) => pattern.test(readFileSync(file, "utf8")));
    expect(hits.map((file) => relative(ROOT, file))).toEqual([]);
  });
});
