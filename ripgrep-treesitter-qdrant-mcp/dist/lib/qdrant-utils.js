const QDRANT_UPSERT_BATCH_SIZE = Number.parseInt(process.env.QDRANT_UPSERT_BATCH_SIZE || "100", 10);
const QDRANT_DELETE_BATCH_SIZE = Number.parseInt(process.env.QDRANT_DELETE_BATCH_SIZE || "500", 10);
export function fakeEmbedding(text, size = 128) {
    const vec = new Array(size).fill(0);
    for (let i = 0; i < text.length; i += 1) {
        const code = text.charCodeAt(i);
        vec[i % size] += ((code % 31) + 1) / 31;
    }
    const norm = Math.sqrt(vec.reduce((acc, value) => acc + value * value, 0)) || 1;
    return vec.map((value) => value / norm);
}
export async function checkQdrantConnection(client) {
    try {
        await client.getCollections();
        return { ok: true, message: 'Qdrant reachable' };
    }
    catch (error) {
        return { ok: false, message: error?.message || 'Unable to connect to Qdrant' };
    }
}
export async function ensureCollection(client, collectionName, vectorSize = 128) {
    const collections = await client.getCollections();
    const exists = collections.collections.some((c) => c.name === collectionName);
    if (!exists) {
        await client.createCollection(collectionName, { vectors: { size: vectorSize, distance: 'Cosine' } });
        return;
    }
    const info = await client.getCollection(collectionName);
    const configVectors = info?.config?.params?.vectors;
    const actualSize = typeof configVectors?.size === 'number' ? configVectors.size : undefined;
    if (typeof actualSize === 'number' && actualSize !== vectorSize) {
        throw new Error(`Qdrant collection ${collectionName} exists with vector size ${actualSize}, expected ${vectorSize}. Delete or reconfigure the collection before re-indexing.`);
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
    const vector = fakeEmbedding(query);
    return client.search(collectionName, { vector, limit, filter, with_payload: true });
}
