import assert from "node:assert/strict";
import test from "node:test";

import {
  createEmbeddingExtractor,
  getEmbeddingExtractorCacheKey,
  getEmbeddingRuntimeConfig,
} from "../dist/lib/embedding-utils.js";

function withEmbeddingDevice(value, callback) {
  const previous = process.env.EMBEDDING_DEVICE;
  if (value === undefined) {
    delete process.env.EMBEDDING_DEVICE;
  } else {
    process.env.EMBEDDING_DEVICE = value;
  }

  try {
    return callback();
  } finally {
    if (previous === undefined) delete process.env.EMBEDDING_DEVICE;
    else process.env.EMBEDDING_DEVICE = previous;
  }
}

test("uses cpu as the portable default embedding device", () => {
  withEmbeddingDevice(undefined, () => {
    assert.equal(getEmbeddingRuntimeConfig().device, "cpu");
  });
});

test("propagates the configured device to pipeline creation", async () => {
  let invocation;
  const config = withEmbeddingDevice("dml", () => getEmbeddingRuntimeConfig());
  const fakePipeline = async (...args) => {
    invocation = args;
    return { fake: true };
  };

  const extractor = await createEmbeddingExtractor(config, fakePipeline);

  assert.deepEqual(extractor, { fake: true });
  assert.equal(invocation[0], "feature-extraction");
  assert.equal(invocation[1], config.model);
  assert.deepEqual(invocation[2], { device: "dml" });
});

test("extractor cache keys include the embedding device", () => {
  const cpu = withEmbeddingDevice("cpu", () => getEmbeddingRuntimeConfig());
  const dml = withEmbeddingDevice("dml", () => getEmbeddingRuntimeConfig());
  assert.notEqual(getEmbeddingExtractorCacheKey(cpu), getEmbeddingExtractorCacheKey(dml));
});

test("rejects unsupported embedding devices early", () => {
  assert.throws(
    () => withEmbeddingDevice("auto", () => getEmbeddingRuntimeConfig()),
    /Unsupported EMBEDDING_DEVICE/,
  );
});
