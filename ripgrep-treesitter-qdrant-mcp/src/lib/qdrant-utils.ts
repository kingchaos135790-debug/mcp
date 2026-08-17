import { QdrantClient } from "@qdrant/js-client-rest";
import { embedQuery, getEmbeddingRuntimeConfig } from "./embedding-utils.js";

export type PointPayload = {
  repoId: string;
  repo: string;
  repoRoot: string;
  path: string;
  symbol: string;
  kind: string;
  language: string;
  startLine: number;
  endLine: number;
  content: string;
};

function positiveBatchSize(value: string | undefined, fallback: number): number {
  const parsed = Number.parseInt(value || "", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function isConnectionReset(error: any): boolean {
  return error?.code === "ECONNRESET" || error?.cause?.code === "ECONNRESET";
}

export function getQdrantUpsertBatchSize(): number {
  return positiveBatchSize(process.env.QDRANT_UPSERT_BATCH_SIZE, 100);
}

export function getQdrantDeleteBatchSize(): number {
  return positiveBatchSize(process.env.QDRANT_DELETE_BATCH_SIZE, 500);
}

export async function checkQdrantConnection(client: QdrantClient): Promise<{ ok: boolean; message: string }> {
  try {
    await client.getCollections();
    return { ok: true, message: "Qdrant reachable" };
  } catch (error: any) {
    return { ok: false, message: error?.message || "Unable to connect to Qdrant" };
  }
}

export async function ensureCollection(
  client: QdrantClient,
  collectionName: string,
  vectorSize = getEmbeddingRuntimeConfig().dimensions,
): Promise<void> {
  const collections = await client.getCollections();
  const exists = collections.collections.some((c) => c.name === collectionName);
  if (!exists) {
    await client.createCollection(collectionName, { vectors: { size: vectorSize, distance: "Cosine" } });
    return;
  }

  const info = await client.getCollection(collectionName);
  const configVectors = (info?.config?.params as any)?.vectors;
  const actualSize = typeof configVectors?.size === "number" ? configVectors.size : undefined;
  if (typeof actualSize === "number" && actualSize !== vectorSize) {
    throw new Error(`Qdrant collection ${collectionName} exists with vector size ${actualSize}, expected ${vectorSize}. Use a new QDRANT_COLLECTION or rebuild the collection before re-indexing.`);
  }
}

export async function upsertChunks(client: QdrantClient, collectionName: string, points: Array<{ id: string; vector: number[]; payload: PointPayload }>): Promise<void> {
  if (points.length === 0) return;

  const batchSize = getQdrantUpsertBatchSize();
  for (let i = 0; i < points.length; i += batchSize) {
    const batch = points.slice(i, i + batchSize);
    try {
      await client.upsert(collectionName, { wait: true, points: batch });
    } catch (error) {
      if (!isConnectionReset(error)) throw error;
      // Streaming indexing can leave the HTTP keep-alive connection idle during a slow
      // embedding batch. Retrying the same point IDs is safe because Qdrant upserts are idempotent.
      await client.upsert(collectionName, { wait: true, points: batch });
    }
  }
}

export async function deletePoints(client: QdrantClient, collectionName: string, pointIds: string[]): Promise<void> {
  if (pointIds.length === 0) return;

  const batchSize = getQdrantDeleteBatchSize();
  for (let i = 0; i < pointIds.length; i += batchSize) {
    const batch = pointIds.slice(i, i + batchSize);
    await client.delete(collectionName, { wait: true, points: batch });
  }
}

export async function deletePointsByFilter(
  client: QdrantClient,
  collectionName: string,
  filter: Record<string, unknown>,
): Promise<void> {
  await client.delete(collectionName, { wait: true, filter });
}

export async function semanticSearch(
  client: QdrantClient,
  collectionName: string,
  query: string,
  limit = 8,
  filter?: Record<string, unknown>,
) {
  const vector = await embedQuery(query);
  return client.search(collectionName, { vector, limit, filter, with_payload: true });
}
