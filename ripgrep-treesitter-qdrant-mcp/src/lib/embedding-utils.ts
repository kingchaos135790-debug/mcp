import path from "node:path";
import { env, pipeline } from "@huggingface/transformers";

export type EmbeddingDevice = "cpu" | "dml";

export type EmbeddingRuntimeConfig = {
  model: string;
  dimensions: number;
  batchSize: number;
  cacheDir: string;
  device: EmbeddingDevice;
  queryPrefix: string;
  pooling: "mean";
  normalized: true;
};

const DEFAULT_MODEL = "Xenova/bge-base-en-v1.5";
const DEFAULT_DIMENSIONS = 768;
const DEFAULT_BATCH_SIZE = 16;
const DEFAULT_DEVICE: EmbeddingDevice = "cpu";
const DEFAULT_QUERY_PREFIX = "Represent this sentence for searching relevant passages: ";
const SUPPORTED_DEVICES = new Set<EmbeddingDevice>(["cpu", "dml"]);

let extractorPromise: Promise<any> | null = null;
let extractorKey = "";

function positiveInt(value: string | undefined, fallback: number): number {
  const parsed = Number.parseInt(value || "", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function embeddingDevice(value: string | undefined): EmbeddingDevice {
  const device = (value || DEFAULT_DEVICE).trim().toLowerCase() as EmbeddingDevice;
  if (!SUPPORTED_DEVICES.has(device)) {
    throw new Error(`Unsupported EMBEDDING_DEVICE=${JSON.stringify(value)}. Expected cpu or dml.`);
  }
  return device;
}

export function getEmbeddingRuntimeConfig(): EmbeddingRuntimeConfig {
  const indexRoot = path.resolve(process.env.INDEX_ROOT || "E:/mcp-index-data");
  return {
    model: (process.env.EMBEDDING_MODEL || DEFAULT_MODEL).trim() || DEFAULT_MODEL,
    dimensions: positiveInt(process.env.EMBEDDING_DIMENSIONS, DEFAULT_DIMENSIONS),
    batchSize: positiveInt(process.env.EMBEDDING_BATCH_SIZE, DEFAULT_BATCH_SIZE),
    cacheDir: path.resolve(process.env.EMBEDDING_CACHE_DIR || path.join(indexRoot, "models")),
    device: embeddingDevice(process.env.EMBEDDING_DEVICE),
    queryPrefix: process.env.EMBEDDING_QUERY_PREFIX ?? DEFAULT_QUERY_PREFIX,
    pooling: "mean",
    normalized: true,
  };
}

export async function createEmbeddingExtractor(
  config: EmbeddingRuntimeConfig,
  pipelineFactory: typeof pipeline = pipeline,
): Promise<any> {
  env.cacheDir = config.cacheDir;
  return pipelineFactory("feature-extraction", config.model, { device: config.device });
}

export function getEmbeddingExtractorCacheKey(config: EmbeddingRuntimeConfig): string {
  return `${config.model}::${config.cacheDir}::${config.device}`;
}

async function getExtractor(config: EmbeddingRuntimeConfig): Promise<any> {
  const key = getEmbeddingExtractorCacheKey(config);
  if (!extractorPromise || extractorKey !== key) {
    extractorKey = key;
    extractorPromise = createEmbeddingExtractor(config);
  }
  return extractorPromise;
}

function validateRows(rows: unknown, expectedCount: number, dimensions: number): number[][] {
  if (!Array.isArray(rows) || rows.length !== expectedCount) {
    throw new Error(`Embedding model returned ${Array.isArray(rows) ? rows.length : "invalid"} rows; expected ${expectedCount}.`);
  }

  return rows.map((row, index) => {
    if (!Array.isArray(row) || row.length !== dimensions || row.some((value) => typeof value !== "number" || !Number.isFinite(value))) {
      throw new Error(`Embedding row ${index} is invalid or does not match the configured ${dimensions} dimensions.`);
    }
    return row as number[];
  });
}

async function embedTexts(texts: string[], query: boolean): Promise<number[][]> {
  if (texts.length === 0) return [];

  const config = getEmbeddingRuntimeConfig();
  const extractor = await getExtractor(config);
  const results: number[][] = [];

  for (let offset = 0; offset < texts.length; offset += config.batchSize) {
    const batch = texts.slice(offset, offset + config.batchSize).map((text) => query ? `${config.queryPrefix}${text}` : text);
    const tensor = await extractor(batch, { pooling: config.pooling, normalize: config.normalized });
    const rows = validateRows(tensor.tolist(), batch.length, config.dimensions);
    results.push(...rows);
  }

  return results;
}

export async function embedDocuments(texts: string[]): Promise<number[][]> {
  return embedTexts(texts, false);
}

export async function embedQuery(text: string): Promise<number[]> {
  const [embedding] = await embedTexts([text], true);
  return embedding;
}
