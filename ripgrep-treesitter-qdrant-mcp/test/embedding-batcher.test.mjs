import assert from "node:assert/strict";
import test from "node:test";

import { EmbeddingBatchQueue } from "../dist/lib/embedding-batcher.js";

test("shares embedding batches across files", async () => {
  const calls = [];
  const assignments = new Map();
  const queue = new EmbeddingBatchQueue(
    2,
    async (texts) => {
      calls.push([...texts]);
      return texts.map((text) => [text.charCodeAt(0)]);
    },
    (value, vector) => assignments.set(value, vector),
    2,
  );

  await queue.add("aa", "file-a:chunk-1");
  await queue.add("bb", "file-b:chunk-1");
  await queue.add("cc", "file-a:chunk-2");
  await queue.add("dd", "file-b:chunk-2");
  await queue.flush();

  assert.deepEqual(calls, [["aa", "bb"], ["cc", "dd"]]);
  assert.deepEqual(assignments.get("file-a:chunk-1"), ["a".charCodeAt(0)]);
  assert.deepEqual(assignments.get("file-b:chunk-2"), ["d".charCodeAt(0)]);
  assert.equal(queue.pendingCount, 0);
});

test("maps vectors back to the correct chunks after length-aware sorting", async () => {
  const assignments = new Map();
  const queue = new EmbeddingBatchQueue(
    2,
    async (texts) => texts.map((text) => [text.length]),
    (value, vector) => assignments.set(value, vector),
    4,
  );

  await queue.add("longest-input", "long");
  await queue.add("x", "short");
  await queue.add("medium", "medium");

  assert.equal(assignments.size, 0, "partial windows should remain queued until flush");
  await queue.flush();

  assert.deepEqual(assignments.get("short"), [1]);
  assert.deepEqual(assignments.get("medium"), [6]);
  assert.deepEqual(assignments.get("long"), [13]);
});

test("rejects an embedding result with the wrong row count", async () => {
  const queue = new EmbeddingBatchQueue(2, async () => [[1]], () => {}, 1);
  await assert.rejects(
    async () => {
      await queue.add("a", 1);
      await queue.add("b", 2);
    },
    /returned 1 vectors; expected 2/,
  );
});
