import path from "node:path";
import { fileURLToPath } from "node:url";
export function getSearchEngineConfig() {
    const qdrantUrl = process.env.QDRANT_URL || "http://127.0.0.1:16333";
    const qdrantCollection = process.env.QDRANT_COLLECTION || "code_chunks_bge_base_en_v1_5";
    const defaultIndexRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../../../mcp-index-data");
    const indexRoot = path.resolve(process.env.INDEX_ROOT || defaultIndexRoot);
    const repositoriesRoot = path.join(indexRoot, "repositories");
    const registryPath = path.join(indexRoot, "repositories.json");
    return {
        qdrantUrl,
        qdrantCollection,
        indexRoot,
        repositoriesRoot,
        registryPath,
    };
}
export function clampLimit(limit, fallback = 8, max = 20) {
    return Number.isFinite(limit) && limit > 0
        ? Math.min(limit, max)
        : fallback;
}
