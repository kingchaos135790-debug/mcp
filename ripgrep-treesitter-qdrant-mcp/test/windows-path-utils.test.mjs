import test from "node:test";
import assert from "node:assert/strict";

import {
  getWindowsReservedDeviceExcludeGlobs,
  isWindowsReservedDevicePath,
} from "../dist/lib/windows-path-utils.js";

test("detects reserved Windows device names", () => {
  assert.equal(isWindowsReservedDevicePath("nul"), true);
  assert.equal(isWindowsReservedDevicePath("C:/repo/aux.txt"), true);
  assert.equal(isWindowsReservedDevicePath("C:/repo/src/note.txt"), false);
});

test("produces rg exclusion globs for reserved names", () => {
  const globs = getWindowsReservedDeviceExcludeGlobs();
  assert.ok(globs.includes("!nul"));
  assert.ok(globs.includes("!**/con.*"));
});
