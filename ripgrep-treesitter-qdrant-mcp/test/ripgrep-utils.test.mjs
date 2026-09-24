import assert from "node:assert/strict";
import test from "node:test";

import { buildRipgrepCoverageArgs } from "../dist/lib/ripgrep-utils.js";

function valuesForFlag(args, flag) {
  const values = [];
  for (let index = 0; index < args.length - 1; index += 1) {
    if (args[index] === flag) values.push(args[index + 1]);
  }
  return values;
}

test("default ripgrep coverage searches source code but not docs", () => {
  const args = buildRipgrepCoverageArgs();
  const globs = valuesForFlag(args, "--glob");

  assert.ok(globs.includes("**/*.ts"));
  assert.ok(globs.includes("**/*.py"));
  assert.ok(!globs.includes("**/*.md"));
  assert.ok(globs.includes("!**/dist/**"));
});

test("default ripgrep coverage excludes stale backup and invalid artifacts", () => {
  const args = buildRipgrepCoverageArgs();
  const globs = valuesForFlag(args, "--glob");

  assert.ok(globs.includes("!**/*.bak"));
  assert.ok(globs.includes("!**/*.bak-*"));
  assert.ok(globs.includes("!**/*.backup"));
  assert.ok(globs.includes("!**/*.old"));
  assert.ok(globs.includes("!**/*.tmp"));
  assert.ok(globs.includes("!**/*.orig"));
  assert.ok(globs.includes("!**/*.rej"));
  assert.ok(globs.includes("!**/*.invalid-*"));
});

test("repository coverage can opt docs and generated files back in", () => {
  const args = buildRipgrepCoverageArgs({
    indexedExtensions: [".ts", ".md"],
    ignoredGlobs: ["**/.git/**"],
    extraIncludeGlobs: ["config/**/*.yaml"],
    maxFileBytes: 1234,
  });
  const globs = valuesForFlag(args, "--glob");

  assert.ok(globs.includes("**/*.md"));
  assert.ok(globs.includes("config/**/*.yaml"));
  assert.ok(!globs.includes("!**/dist/**"));
  assert.ok(globs.includes("!**/*.bak-*"));

  const maxFileSizeIndex = args.indexOf("--max-filesize");
  assert.notEqual(maxFileSizeIndex, -1);
  assert.equal(args[maxFileSizeIndex + 1], "1234");
});
