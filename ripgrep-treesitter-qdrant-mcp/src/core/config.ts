import path from "node:path";

export type SearchEngineConfig = {
  qdrantUrl: string;
  qdrantCollection: string;
  indexRoot: string;
  repositoriesRoot: string;
  registryPath: string;
  localLexicalIndexPath: string;
};

export function getSearchEngineConfig(): SearchEngineConfig {
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

export function clampLimit(limit: number | undefined, fallback = 8, max = 20): number {
  return Number.isFinite(limit) && (limit as number) > 0
    ? Math.min(limit as number, max)
    : fallback;
}
