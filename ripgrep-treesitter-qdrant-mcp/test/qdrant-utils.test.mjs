import assert from "node:assert/strict";
import test from "node:test";

import { upsertChunks } from "../dist/lib/qdrant-utils.js";

function point(id) {
  return {
    id,
    vector: [1],
    payload: {
      repoId: "repo",
      repo: "repo",
      repoRoot: "C:/repo",
      path: "file.ts",
      symbol: "symbol",
      kind: "function",
      language: "typescript",
      startLine: 1,
      endLine: 1,
      content: "content",
    },
  };
}

test("retries one idempotent Qdrant upsert after ECONNRESET", async () => {
  let attempts = 0;
  const client = {
    async upsert() {
      attempts += 1;
      if (attempts === 1) {
        const error = new Error("fetch failed");
        error.cause = { code: "ECONNRESET" };
        throw error;
      }
    },
  };

  await upsertChunks(client, "collection", [point("00000000-0000-5000-8000-000000000001")]);
  assert.equal(attempts, 2);
});

test("does not retry non-connection-reset Qdrant failures", async () => {
  let attempts = 0;
  const expected = new Error("bad request");
  const client = {
    async upsert() {
      attempts += 1;
      throw expected;
    },
  };

  await assert.rejects(
    () => upsertChunks(client, "collection", [point("00000000-0000-5000-8000-000000000001")]),
    expected,
  );
  assert.equal(attempts, 1);
});
