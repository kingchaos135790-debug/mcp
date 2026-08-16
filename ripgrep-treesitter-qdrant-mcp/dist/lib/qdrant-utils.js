import { embedQuery, getEmbeddingRuntimeConfig } from "./embedding-utils.js";
const QDRANT_UPSERT_BATCH_SIZE = Number.parseInt(process.env.QDRANT_UPSERT_BATCH_SIZE || "100", 10);
const QDRANT_DELETE_BATCH_SIZE = Number.parseInt(process.env.QDRANT_DELETE_BATCH_SIZE || "500", 10);
export async function checkQdrantConnection(client) {
    try {
        await client.getCollections();
        return { ok: true, message: "Qdrant reachable" };
    }
    catch (error) {
        return { ok: false, message: error?.message || "Unable to connect to Qdrant" };
    }
}
export async function ensureCollection(client, collectionName, vectorSize = getEmbeddingRuntimeConfig().dimensions) {
    const collections = await client.getCollections();
    const exists = collections.collections.some((c) => c.name === collectionName);
    if (!exists) {
        await client.createCollection(collectionName, { vectors: { size: vectorSize, distance: "Cosine" } });
        return;
    }
    const info = await client.getCollection(collectionName);
    const configVectors = info?.config?.params?.vectors;
    const actualSize = typeof configVectors?.size === "number" ? configVectors.size : undefined;
    if (typeof actualSize === "number" && actualSize !== vectorSize) {
        throw new Error(`Qdrant collection ${collectionName} exists with vector size ${actualSize}, expected ${vectorSize}. Use a new QDRANT_COLLECTION or rebuild the collection before re-indexing.`);
    }
}
export async function upsertChunks(client, collectionName, points) {
    if (points.length === 0)
        return;
    const batchSize = Number.isFinite(QDRANT_UPSERT_BATCH_SIZE) && QDRANT_UPSERT_BATCH_SIZE > 0
        ? QDRANT_UPSERT_BATCH_SIZE
        : 100;
    for (let i = 0; i < points.length; i += batchSize) {
        const batch = points.slice(i, i + batchSize);
        await client.upsert(collectionName, { wait: true, points: batch });
    }
}
export async function deletePoints(client, collectionName, pointIds) {
    if (pointIds.length === 0)
        return;
    const batchSize = Number.isFinite(QDRANT_DELETE_BATCH_SIZE) && QDRANT_DELETE_BATCH_SIZE > 0
        ? QDRANT_DELETE_BATCH_SIZE
        : 500;
    for (let i = 0; i < pointIds.length; i += batchSize) {
        const batch = pointIds.slice(i, i + batchSize);
        await client.delete(collectionName, { wait: true, points: batch });
    }
}
export async function deletePointsByFilter(client, collectionName, filter) {
    await client.delete(collectionName, { wait: true, filter });
}
export async function semanticSearch(client, collectionName, query, limit = 8, filter) {
    const vector = await embedQuery(query);
    return client.search(collectionName, { vector, limit, filter, with_payload: true });
}
