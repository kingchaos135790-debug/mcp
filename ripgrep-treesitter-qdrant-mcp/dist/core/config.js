import path from "node:path";
export function getSearchEngineConfig() {
    const qdrantUrl = process.env.QDRANT_URL || "http://127.0.0.1:16333";
    const qdrantCollection = process.env.QDRANT_COLLECTION || "code_chunks";
    const indexRoot = path.resolve(process.env.INDEX_ROOT || "E:/mcp-index-data");
    const repositoriesRoot = path.join(indexRoot, "repositories");
    const registryPath = path.join(indexRoot, "repositories.json");
    const localLexicalIndexPath = path.join(indexRoot, "local-lexical-index.json");
    return {
        qdrantUrl,
        qdrantCollection,
        indexRoot,
        repositoriesRoot,
        registryPath,
        localLexicalIndexPath,
    };
}
export function clampLimit(limit, fallback = 8, max = 20) {
    return Number.isFinite(limit) && limit > 0
        ? Math.min(limit, max)
        : fallback;
}
