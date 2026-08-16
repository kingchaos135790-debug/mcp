import path from "node:path";
import { env, pipeline } from "@huggingface/transformers";
const DEFAULT_MODEL = "Xenova/bge-small-en-v1.5";
const DEFAULT_DIMENSIONS = 384;
const DEFAULT_BATCH_SIZE = 16;
const DEFAULT_QUERY_PREFIX = "Represent this sentence for searching relevant passages: ";
let extractorPromise = null;
let extractorKey = "";
function positiveInt(value, fallback) {
    const parsed = Number.parseInt(value || "", 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}
export function getEmbeddingRuntimeConfig() {
    const indexRoot = path.resolve(process.env.INDEX_ROOT || "E:/mcp-index-data");
    return {
        model: (process.env.EMBEDDING_MODEL || DEFAULT_MODEL).trim() || DEFAULT_MODEL,
        dimensions: positiveInt(process.env.EMBEDDING_DIMENSIONS, DEFAULT_DIMENSIONS),
        batchSize: positiveInt(process.env.EMBEDDING_BATCH_SIZE, DEFAULT_BATCH_SIZE),
        cacheDir: path.resolve(process.env.EMBEDDING_CACHE_DIR || path.join(indexRoot, "models")),
        queryPrefix: process.env.EMBEDDING_QUERY_PREFIX ?? DEFAULT_QUERY_PREFIX,
        pooling: "mean",
        normalized: true,
    };
}
async function getExtractor(config) {
    const key = `${config.model}::${config.cacheDir}`;
    if (!extractorPromise || extractorKey !== key) {
        env.cacheDir = config.cacheDir;
        extractorKey = key;
        extractorPromise = pipeline("feature-extraction", config.model);
    }
    return extractorPromise;
}
function validateRows(rows, expectedCount, dimensions) {
    if (!Array.isArray(rows) || rows.length !== expectedCount) {
        throw new Error(`Embedding model returned ${Array.isArray(rows) ? rows.length : "invalid"} rows; expected ${expectedCount}.`);
    }
    return rows.map((row, index) => {
        if (!Array.isArray(row) || row.length !== dimensions || row.some((value) => typeof value !== "number" || !Number.isFinite(value))) {
            throw new Error(`Embedding row ${index} is invalid or does not match the configured ${dimensions} dimensions.`);
        }
        return row;
    });
}
async function embedTexts(texts, query) {
    if (texts.length === 0)
        return [];
    const config = getEmbeddingRuntimeConfig();
    const extractor = await getExtractor(config);
    const results = [];
    for (let offset = 0; offset < texts.length; offset += config.batchSize) {
        const batch = texts.slice(offset, offset + config.batchSize).map((text) => query ? `${config.queryPrefix}${text}` : text);
        const tensor = await extractor(batch, { pooling: config.pooling, normalize: config.normalized });
        const rows = validateRows(tensor.tolist(), batch.length, config.dimensions);
        results.push(...rows);
    }
    return results;
}
export async function embedDocuments(texts) {
    return embedTexts(texts, false);
}
export async function embedQuery(text) {
    const [embedding] = await embedTexts([text], true);
    return embedding;
}
