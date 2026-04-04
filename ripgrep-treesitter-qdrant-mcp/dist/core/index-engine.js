import fs from "node:fs/promises";
import path from "node:path";
import { QdrantClient } from "@qdrant/js-client-rest";
import { getSearchEngineConfig } from "./config.js";
import { getRepoStoragePaths, hashText, removeIndexedRepository, resolveRepository, upsertIndexedRepository, writeRepoManifest, readRepoManifest, } from "./repository-store.js";
import { checkQdrantConnection, deletePoints, deletePointsByFilter, ensureCollection, fakeEmbedding, upsertChunks, } from "../lib/qdrant-utils.js";
import { listSourceFiles, readText, toPosixRelative } from "../lib/fs-utils.js";
import { extractCodeChunks } from "../lib/tree-sitter-utils.js";
import { buildLocalLexicalDocument, writeLocalLexicalIndex } from "../lib/local-lexical-utils.js";
import { hasRipgrep } from "../lib/ripgrep-utils.js";
function buildPointId(repoId, relativePath, chunk) {
    const hex = hashText([
        repoId,
        relativePath,
        chunk.symbol,
        chunk.kind,
        String(chunk.startLine),
        String(chunk.endLine),
        chunk.text,
    ].join("\n")).slice(0, 32).split("");
    hex[12] = "5";
    hex[16] = ((parseInt(hex[16], 16) & 0x3) | 0x8).toString(16);
    return `${hex.slice(0, 8).join("")}-${hex.slice(8, 12).join("")}-${hex.slice(12, 16).join("")}-${hex.slice(16, 20).join("")}-${hex.slice(20, 32).join("")}`;
}
function createEmptyManifest(repoId, repoName, repoRoot) {
    return {
        version: 1,
        repoId,
        repoName,
        repoRoot,
        indexedAt: new Date(0).toISOString(),
        fileCount: 0,
        files: {},
    };
}
function buildRepoFilter(repoId) {
    return {
        must: [
            {
                key: "repoId",
                match: {
                    value: repoId,
                },
            },
        ],
    };
}
export async function indexRepository(repoRootInput) {
    const config = getSearchEngineConfig();
    const repoRoot = path.resolve(repoRootInput || process.env.REPO_ROOT || ".");
    const storage = getRepoStoragePaths(config, repoRoot);
    const indexedAt = new Date().toISOString();
    await fs.mkdir(storage.repoDir, { recursive: true });
    const client = new QdrantClient({ url: config.qdrantUrl });
    const qdrantStatus = await checkQdrantConnection(client);
    if (!qdrantStatus.ok) {
        throw new Error(`Qdrant is not reachable at ${config.qdrantUrl}. ${qdrantStatus.message}`);
    }
    await ensureCollection(client, config.qdrantCollection);
    const previousManifest = await readRepoManifest(storage.manifestPath)
        ?? createEmptyManifest(storage.repoId, storage.repoName, storage.repoRoot);
    const files = await listSourceFiles(repoRoot);
    const seenPaths = new Set();
    const nextFiles = {};
    const pointsToUpsert = [];
    const pointIdsToDelete = new Set();
    let changedFiles = 0;
    let unchangedFiles = 0;
    for (const file of files) {
        const relativePath = toPosixRelative(repoRoot, file);
        seenPaths.add(relativePath);
        const stat = await fs.stat(file);
        const existing = previousManifest.files[relativePath];
        const existingDocument = existing?.document
            ? {
                ...existing.document,
                repoId: storage.repoId,
                repoName: storage.repoName,
            }
            : undefined;
        if (existing && existing.size === stat.size && existing.mtimeMs === stat.mtimeMs && existingDocument) {
            nextFiles[relativePath] = {
                ...existing,
                document: existingDocument,
            };
            unchangedFiles += 1;
            continue;
        }
        const source = await readText(file);
        const contentHash = hashText(source);
        if (existing && existing.hash === contentHash && existingDocument) {
            nextFiles[relativePath] = {
                ...existing,
                size: stat.size,
                mtimeMs: stat.mtimeMs,
                document: existingDocument,
            };
            unchangedFiles += 1;
            continue;
        }
        changedFiles += 1;
        for (const pointId of existing?.qdrantPointIds || []) {
            pointIdsToDelete.add(pointId);
        }
        const chunks = extractCodeChunks(file, source);
        const qdrantPointIds = [];
        for (const chunk of chunks) {
            const id = buildPointId(storage.repoId, relativePath, chunk);
            qdrantPointIds.push(id);
            pointsToUpsert.push({
                id,
                vector: fakeEmbedding(`${relativePath}\n${chunk.symbol}\n${chunk.text}`),
                payload: {
                    repoId: storage.repoId,
                    repo: storage.repoName,
                    repoRoot: storage.repoRoot,
                    path: relativePath,
                    symbol: chunk.symbol,
                    kind: chunk.kind,
                    language: chunk.language,
                    startLine: chunk.startLine,
                    endLine: chunk.endLine,
                    content: chunk.text,
                },
            });
        }
        nextFiles[relativePath] = {
            path: relativePath,
            hash: contentHash,
            size: stat.size,
            mtimeMs: stat.mtimeMs,
            qdrantPointIds,
            document: buildLocalLexicalDocument(repoRoot, file, source, {
                repoId: storage.repoId,
                repoName: storage.repoName,
            }),
            updatedAt: indexedAt,
        };
    }
    let deletedFiles = 0;
    for (const [relativePath, record] of Object.entries(previousManifest.files)) {
        if (seenPaths.has(relativePath)) {
            continue;
        }
        deletedFiles += 1;
        for (const pointId of record.qdrantPointIds) {
            pointIdsToDelete.add(pointId);
        }
    }
    const deletedPointIds = Array.from(pointIdsToDelete);
    await deletePoints(client, config.qdrantCollection, deletedPointIds);
    await upsertChunks(client, config.qdrantCollection, pointsToUpsert);
    const documents = Object.values(nextFiles)
        .sort((a, b) => a.path.localeCompare(b.path))
        .map((record) => record.document);
    await writeLocalLexicalIndex(storage.localLexicalIndexPath, repoRoot, documents, {
        repoId: storage.repoId,
        repoName: storage.repoName,
    });
    const manifest = {
        version: 1,
        repoId: storage.repoId,
        repoName: storage.repoName,
        repoRoot: storage.repoRoot,
        indexedAt,
        fileCount: documents.length,
        files: nextFiles,
    };
    await writeRepoManifest(storage.manifestPath, manifest);
    await upsertIndexedRepository(config, {
        repoId: storage.repoId,
        repoName: storage.repoName,
        repoRoot: storage.repoRoot,
        indexedAt,
        fileCount: documents.length,
        manifestPath: storage.manifestPath,
        localLexicalIndexPath: storage.localLexicalIndexPath,
        zoektIndexRoot: storage.zoektIndexRoot,
    });
    const ripgrepAvailable = await hasRipgrep();
    return {
        repoId: storage.repoId,
        repoName: storage.repoName,
        repoRoot: storage.repoRoot,
        indexedFiles: files.length,
        changedFiles,
        unchangedFiles,
        deletedFiles,
        qdrant: {
            collection: config.qdrantCollection,
            upsertedPoints: pointsToUpsert.length,
            deletedPoints: deletedPointIds.length,
        },
        localLexicalIndex: {
            ok: true,
            path: storage.localLexicalIndexPath,
            documents: documents.length,
        },
        lexicalSearch: {
            backend: "ripgrep",
            available: ripgrepAvailable,
            message: ripgrepAvailable
                ? "ripgrep is available for lexical search"
                : "ripgrep is not installed; local lexical fallback remains available",
        },
    };
}
export async function removeIndexedRepositoryData(reference) {
    const config = getSearchEngineConfig();
    const normalizedReference = String(reference || process.env.REPO_ROOT || ".").trim();
    const resolvedReference = path.resolve(normalizedReference);
    let indexedRepository;
    try {
        indexedRepository = await resolveRepository(config, normalizedReference);
    }
    catch {
        indexedRepository = undefined;
    }
    const storage = getRepoStoragePaths(config, indexedRepository?.repoRoot || resolvedReference);
    const repoId = indexedRepository?.repoId || storage.repoId;
    const repoName = indexedRepository?.repoName || storage.repoName;
    const repoRoot = indexedRepository?.repoRoot || storage.repoRoot;
    const repoDir = indexedRepository?.manifestPath ? path.dirname(indexedRepository.manifestPath) : storage.repoDir;
    const qdrant = new QdrantClient({ url: config.qdrantUrl });
    const qdrantStatus = await checkQdrantConnection(qdrant);
    if (!qdrantStatus.ok) {
        throw new Error(`Qdrant is not reachable at ${config.qdrantUrl}. ${qdrantStatus.message}`);
    }
    await deletePointsByFilter(qdrant, config.qdrantCollection, buildRepoFilter(repoId));
    await fs.rm(repoDir, { recursive: true, force: true });
    await removeIndexedRepository(config, repoId);
    return {
        repoId,
        repoName,
        repoRoot,
        removedFromRegistry: true,
        removedArtifacts: true,
        removedVectors: true,
        repoDir,
        qdrantCollection: config.qdrantCollection,
    };
}
