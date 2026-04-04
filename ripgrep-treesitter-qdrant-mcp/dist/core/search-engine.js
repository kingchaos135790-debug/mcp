import path from "node:path";
import { QdrantClient } from "@qdrant/js-client-rest";
import { clampLimit, getSearchEngineConfig } from "./config.js";
import { listIndexedRepositories, resolveRepository } from "./repository-store.js";
import { checkQdrantConnection, semanticSearch } from "../lib/qdrant-utils.js";
import { readLocalLexicalIndex, searchLocalLexicalDocuments } from "../lib/local-lexical-utils.js";
import { hasRipgrep, queryRipgrep } from "../lib/ripgrep-utils.js";
function formatSemantic(hit) {
    return {
        score: hit.score,
        ...(hit.payload || {}),
    };
}
function fuseResults(semantic, lexical) {
    const seen = new Set();
    const fused = [];
    for (const hit of semantic) {
        const key = `${hit.repoId || ""}::${hit.path || ""}::${hit.symbol || ""}::${hit.startLine || ""}`;
        if (!seen.has(key)) {
            seen.add(key);
            fused.push({ source: "semantic", ...hit });
        }
    }
    for (const hit of lexical) {
        const key = `${hit.repoId || ""}::${hit.file || ""}::${hit.line || ""}`;
        if (!seen.has(key)) {
            seen.add(key);
            fused.push({ source: hit.backend || "lexical", ...hit });
        }
    }
    return fused;
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
function normalizeCaseMode(caseMode) {
    switch (caseMode) {
        case "ignore":
        case "sensitive":
            return caseMode;
        case "smart":
        default:
            return "smart";
    }
}
async function resolveLexicalSearch(query, limit, repo, caseMode = "smart") {
    const config = getSearchEngineConfig();
    const ripgrepAvailable = await hasRipgrep();
    const repositories = await listIndexedRepositories(config);
    const selectedRepository = await resolveRepository(config, repo);
    const targetRepositories = selectedRepository ? [selectedRepository] : repositories;
    if (ripgrepAvailable) {
        try {
            const hits = [];
            for (const targetRepository of targetRepositories) {
                const repoHits = await queryRipgrep(targetRepository.repoRoot, query, limit, {
                    repoId: targetRepository.repoId,
                    repoName: targetRepository.repoName,
                }, caseMode);
                hits.push(...repoHits);
                if (hits.length >= limit) {
                    break;
                }
            }
            return {
                backend: "ripgrep",
                hits: hits.slice(0, limit),
                status: {
                    ripgrepAvailable: true,
                    ripgrepMessage: "ripgrep available",
                    targetedRepoIds: targetRepositories.map((item) => item.repoId),
                    repositoryCount: repositories.length,
                },
            };
        }
        catch (error) {
            const fallback = await resolveLocalLexicalSearch(targetRepositories, repositories, query, limit);
            return {
                ...fallback,
                status: {
                    ...fallback.status,
                    ripgrepAvailable: true,
                    ripgrepMessage: error?.message || "ripgrep search failed",
                },
            };
        }
    }
    const fallback = await resolveLocalLexicalSearch(targetRepositories, repositories, query, limit);
    return {
        ...fallback,
        status: {
            ...fallback.status,
            ripgrepAvailable: false,
            ripgrepMessage: "ripgrep is not installed",
        },
    };
}
async function resolveLocalLexicalSearch(targetRepositories, repositories, query, limit) {
    const documents = [];
    const availableRepositories = [];
    for (const targetRepository of targetRepositories) {
        const index = await readLocalLexicalIndex(targetRepository.localLexicalIndexPath);
        if (!index) {
            continue;
        }
        availableRepositories.push(targetRepository.repoId);
        documents.push(...index.documents.map((document) => ({
            ...document,
            repoId: document.repoId ?? index.repoId ?? targetRepository.repoId,
            repoName: document.repoName ?? index.repoName ?? targetRepository.repoName,
        })));
    }
    if (!documents.length) {
        return {
            backend: "none",
            hits: [],
            status: {
                targetedRepoIds: targetRepositories.map((item) => item.repoId),
                repositoryCount: repositories.length,
                localIndexAvailable: false,
            },
        };
    }
    return {
        backend: "local",
        hits: searchLocalLexicalDocuments(documents, query, limit),
        status: {
            targetedRepoIds: targetRepositories.map((item) => item.repoId),
            availableRepoIds: availableRepositories,
            repositoryCount: repositories.length,
            localIndexAvailable: true,
            localDocumentCount: documents.length,
        },
    };
}
export async function semanticCodeSearch(query, limit, repo) {
    const config = getSearchEngineConfig();
    const qdrant = new QdrantClient({ url: config.qdrantUrl });
    const cappedLimit = clampLimit(limit);
    const repository = await resolveRepository(config, repo);
    const hits = await semanticSearch(qdrant, config.qdrantCollection, String(query), cappedLimit, repository ? buildRepoFilter(repository.repoId) : undefined);
    return hits.map(formatSemantic);
}
export async function lexicalCodeSearch(query, limit, repo, caseMode) {
    const cappedLimit = clampLimit(limit);
    return resolveLexicalSearch(String(query), cappedLimit, repo, normalizeCaseMode(caseMode));
}
export async function hybridCodeSearch(query, limit, repo) {
    const config = getSearchEngineConfig();
    const qdrant = new QdrantClient({ url: config.qdrantUrl });
    const cappedLimit = clampLimit(limit);
    const repository = await resolveRepository(config, repo);
    const semantic = await semanticSearch(qdrant, config.qdrantCollection, String(query), cappedLimit, repository ? buildRepoFilter(repository.repoId) : undefined);
    const formattedSemantic = semantic.map(formatSemantic);
    const lexical = await resolveLexicalSearch(String(query), cappedLimit, repo);
    return {
        semantic: formattedSemantic,
        lexical: lexical.hits,
        fused: fuseResults(formattedSemantic, lexical.hits),
        status: {
            qdrantCollection: config.qdrantCollection,
            repoFilter: repository?.repoId,
            lexicalBackend: lexical.backend,
            ...lexical.status,
        },
    };
}
export async function listIndexedCodebases() {
    const config = getSearchEngineConfig();
    const repositories = await listIndexedRepositories(config);
    return repositories.map((repository) => ({
        repoId: repository.repoId,
        repoName: repository.repoName,
        repoRoot: repository.repoRoot,
        indexedAt: repository.indexedAt,
        fileCount: repository.fileCount,
        localLexicalIndexPath: repository.localLexicalIndexPath,
        zoektIndexRoot: repository.zoektIndexRoot,
    }));
}
export async function searchEngineHealth() {
    const config = getSearchEngineConfig();
    const qdrant = new QdrantClient({ url: config.qdrantUrl });
    const ripgrepAvailable = await hasRipgrep();
    const qdrantStatus = await checkQdrantConnection(qdrant);
    const repositories = await listIndexedRepositories(config);
    return {
        cwd: process.cwd(),
        qdrantUrl: config.qdrantUrl,
        qdrantCollection: config.qdrantCollection,
        qdrantReachable: qdrantStatus.ok,
        qdrantMessage: qdrantStatus.message,
        ripgrepAvailable,
        ripgrepMessage: ripgrepAvailable ? "ripgrep available" : "ripgrep is not installed",
        indexRoot: config.indexRoot,
        repositoriesRoot: config.repositoriesRoot,
        registryPath: config.registryPath,
        legacyLocalLexicalIndexPath: config.localLexicalIndexPath,
        repositoryCount: repositories.length,
        repositories: repositories.map((repository) => ({
            repoId: repository.repoId,
            repoName: repository.repoName,
            repoRoot: repository.repoRoot,
            indexedAt: repository.indexedAt,
            fileCount: repository.fileCount,
        })),
        repoHint: path.resolve(process.env.REPO_ROOT || "."),
    };
}



