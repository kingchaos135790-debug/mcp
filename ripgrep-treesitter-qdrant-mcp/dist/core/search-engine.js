import path from "node:path";
import { QdrantClient } from "@qdrant/js-client-rest";
import { clampLimit, getSearchEngineConfig } from "./config.js";
import { listIndexedRepositories, readRepoManifest, resolveRepository } from "./repository-store.js";
import { checkQdrantConnection, semanticSearch } from "../lib/qdrant-utils.js";
import { readLocalLexicalIndex, searchLocalLexicalDocuments } from "../lib/local-lexical-utils.js";
import { hasRipgrep, queryRipgrep } from "../lib/ripgrep-utils.js";
import { getEmbeddingRuntimeConfig } from "../lib/embedding-utils.js";
function formatSemantic(hit) {
    return {
        score: hit.score,
        ...(hit.payload || {}),
    };
}
const HYBRID_RRF_K = parsePositiveNumber(process.env.HYBRID_RRF_K, 60);
const HYBRID_SEMANTIC_WEIGHT = parsePositiveNumber(process.env.HYBRID_SEMANTIC_WEIGHT, 1);
const HYBRID_LEXICAL_WEIGHT = parsePositiveNumber(process.env.HYBRID_LEXICAL_WEIGHT, 1.2);
function parsePositiveNumber(value, fallback) {
    const parsed = Number(value);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}
function normalizeResultPath(result) {
    return String(result.path || result.file || "")
        .replace(/^\.([\\/])/, "")
        .replace(/\\/g, "/")
        .toLowerCase();
}
function resultRepoId(result) {
    return String(result.repoId || result.repo || result.repoName || "").toLowerCase();
}
function resultLineRange(result) {
    const line = Number(result.line);
    if (Number.isFinite(line) && line > 0) {
        return { start: line, end: line };
    }
    const start = Number(result.startLine);
    const end = Number(result.endLine);
    return {
        start: Number.isFinite(start) && start > 0 ? start : null,
        end: Number.isFinite(end) && end > 0 ? end : Number.isFinite(start) && start > 0 ? start : null,
    };
}
function sameResultIdentity(left, right) {
    const leftRange = resultLineRange(left);
    const rightRange = resultLineRange(right);
    return resultRepoId(left) === resultRepoId(right)
        && normalizeResultPath(left) === normalizeResultPath(right)
        && leftRange.start === rightRange.start
        && String(left.symbol || "") === String(right.symbol || "");
}
function sameLogicalResult(left, right) {
    if (resultRepoId(left) !== resultRepoId(right) || normalizeResultPath(left) !== normalizeResultPath(right)) {
        return false;
    }
    const leftRange = resultLineRange(left);
    const rightRange = resultLineRange(right);
    if (leftRange.start === null || leftRange.end === null || rightRange.start === null || rightRange.end === null) {
        return String(left.symbol || "") === String(right.symbol || "");
    }
    return leftRange.start <= rightRange.end && rightRange.start <= leftRange.end;
}
function resultSpan(result) {
    const range = resultLineRange(result);
    if (range.start === null || range.end === null) {
        return Number.MAX_SAFE_INTEGER;
    }
    return Math.max(0, range.end - range.start);
}
function reciprocalRank(rank, weight) {
    return weight / (HYBRID_RRF_K + rank);
}
function mergeResultFields(primary, secondary) {
    const merged = { ...secondary, ...primary };
    const filePath = primary.filePath || primary.path || primary.file || secondary.filePath || secondary.path || secondary.file;
    if (filePath) {
        merged.filePath = filePath;
    }
    if (!merged.snippet && secondary.snippet) {
        merged.snippet = secondary.snippet;
    }
    if (!merged.text && secondary.text) {
        merged.text = secondary.text;
    }
    return merged;
}
export function fuseResults(semantic, lexical, limit = 8) {
    const candidates = [];
    const addResult = (result, source, rank, weight) => {
        let candidate = candidates.find((item) => item.sources.has(source) && sameResultIdentity(item.result, result));
        if (!candidate) {
            candidate = candidates
                .filter((item) => !item.sources.has(source) && sameLogicalResult(item.result, result))
                .sort((a, b) => resultSpan(a.result) - resultSpan(b.result))[0];
        }
        if (!candidate) {
            candidate = {
                result: { ...result },
                score: 0,
                sources: new Set(),
            };
            candidates.push(candidate);
        }
        else if (source === "semantic") {
            candidate.result = mergeResultFields(result, candidate.result);
        }
        else {
            candidate.result = mergeResultFields(candidate.result, result);
        }
        candidate.score += reciprocalRank(rank, weight);
        candidate.sources.add(source);
        if (source === "semantic") {
            candidate.semanticRank = Math.min(candidate.semanticRank ?? rank, rank);
        }
        else {
            candidate.lexicalRank = Math.min(candidate.lexicalRank ?? rank, rank);
        }
    };
    semantic.forEach((result, index) => addResult(result, "semantic", index + 1, HYBRID_SEMANTIC_WEIGHT));
    lexical.forEach((result, index) => addResult(result, "lexical", index + 1, HYBRID_LEXICAL_WEIGHT));
    const maxScore = (HYBRID_SEMANTIC_WEIGHT + HYBRID_LEXICAL_WEIGHT) / (HYBRID_RRF_K + 1);
    return candidates
        .sort((a, b) => b.score - a.score
        || (a.semanticRank ?? Number.MAX_SAFE_INTEGER) - (b.semanticRank ?? Number.MAX_SAFE_INTEGER)
        || (a.lexicalRank ?? Number.MAX_SAFE_INTEGER) - (b.lexicalRank ?? Number.MAX_SAFE_INTEGER))
        .slice(0, Math.max(1, limit))
        .map((candidate) => ({
        ...candidate.result,
        source: candidate.sources.size > 1 ? "hybrid" : Array.from(candidate.sources)[0],
        sources: Array.from(candidate.sources),
        fusionScore: Number((candidate.score / maxScore).toFixed(6)),
        semanticRank: candidate.semanticRank,
        lexicalRank: candidate.lexicalRank,
    }));
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
function uniqueWarnings(values) {
    return Array.from(new Set(values.filter(Boolean)));
}
function queryLooksLikeDocs(query) {
    const normalized = query.toLowerCase();
    return /\b(proposal|readme|docs?|documentation|markdown|mdx)\b/.test(normalized) || normalized.includes(".md");
}
function queryLooksLikeGenerated(query) {
    const normalized = query.toLowerCase();
    return /\b(generated|dist|build|coverage|node_modules|bin|obj)\b/.test(normalized) || normalized.includes(".next");
}
async function buildQueryCoverageWarnings(query, targetRepositories) {
    const docsQuery = queryLooksLikeDocs(query);
    const generatedQuery = queryLooksLikeGenerated(query);
    if (!docsQuery && !generatedQuery) {
        return [];
    }
    let missingCoverage = 0;
    let docsExcluded = 0;
    let generatedExcluded = 0;
    const docsExtensions = new Set([".md", ".mdx", ".rst", ".adoc", ".txt"]);
    for (const targetRepository of targetRepositories) {
        const manifest = await readRepoManifest(targetRepository.manifestPath);
        const coverage = manifest?.coverage;
        if (!coverage) {
            missingCoverage += 1;
            continue;
        }
        const indexedExtensions = new Set((coverage.indexedExtensions || []).map((extension) => extension.toLowerCase()));
        const docsCovered = Boolean(coverage.includeDocs) || Array.from(docsExtensions).some((extension) => indexedExtensions.has(extension));
        if (docsQuery && !docsCovered) {
            docsExcluded += 1;
        }
        if (generatedQuery && !coverage.includeGenerated) {
            generatedExcluded += 1;
        }
    }
    const warnings = [];
    if (docsExcluded > 0) {
        warnings.push("Query appears to target documentation, but documentation files are outside indexed coverage for one or more selected repositories. Run index_repository with includeDocs=true or add relevant extraExtensions to index them.");
    }
    if (generatedExcluded > 0) {
        warnings.push("Query appears to target generated or build output, but generated/build paths are excluded from indexed coverage for one or more selected repositories.");
    }
    if (missingCoverage > 0) {
        warnings.push("Coverage metadata is missing for one or more selected repositories. Re-run index_repository with the current engine to get precise coverage warnings.");
    }
    return uniqueWarnings(warnings);
}
async function resolveLexicalSearch(query, limit, repo, caseMode = "smart") {
    const config = getSearchEngineConfig();
    const ripgrepAvailable = await hasRipgrep();
    const repositories = await listIndexedRepositories(config);
    const selectedRepository = await resolveRepository(config, repo);
    const targetRepositories = selectedRepository ? [selectedRepository] : repositories;
    const coverageWarnings = await buildQueryCoverageWarnings(query, targetRepositories);
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
                    warnings: coverageWarnings,
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
                    warnings: coverageWarnings,
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
            warnings: coverageWarnings,
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
    const embedding = getEmbeddingRuntimeConfig();
    const qdrant = new QdrantClient({ url: config.qdrantUrl });
    const cappedLimit = clampLimit(limit);
    const repository = await resolveRepository(config, repo);
    const semantic = await semanticSearch(qdrant, config.qdrantCollection, String(query), cappedLimit, repository ? buildRepoFilter(repository.repoId) : undefined);
    const formattedSemantic = semantic.map(formatSemantic);
    const lexical = await resolveLexicalSearch(String(query), cappedLimit, repo);
    return {
        semantic: formattedSemantic,
        lexical: lexical.hits,
        fused: fuseResults(formattedSemantic, lexical.hits, cappedLimit),
        status: {
            qdrantCollection: config.qdrantCollection,
            embedding: {
                model: embedding.model,
                dimensions: embedding.dimensions,
                pooling: embedding.pooling,
                normalized: embedding.normalized,
            },
            repoFilter: repository?.repoId,
            lexicalBackend: lexical.backend,
            fusion: {
                algorithm: "weighted_rrf",
                rrfK: HYBRID_RRF_K,
                semanticWeight: HYBRID_SEMANTIC_WEIGHT,
                lexicalWeight: HYBRID_LEXICAL_WEIGHT,
            },
            ...lexical.status,
        },
    };
}
export async function listIndexedCodebases() {
    const config = getSearchEngineConfig();
    const repositories = await listIndexedRepositories(config);
    return Promise.all(repositories.map(async (repository) => {
        const manifest = await readRepoManifest(repository.manifestPath);
        return {
            repoId: repository.repoId,
            repoName: repository.repoName,
            repoRoot: repository.repoRoot,
            indexedAt: repository.indexedAt,
            fileCount: repository.fileCount,
            localLexicalIndexPath: repository.localLexicalIndexPath,
            zoektIndexRoot: repository.zoektIndexRoot,
            coverage: manifest?.coverage,
            freshnessStrategy: manifest?.freshnessStrategy,
            semanticIndex: manifest?.semanticIndex,
        };
    }));
}
export async function searchEngineHealth() {
    const config = getSearchEngineConfig();
    const embedding = getEmbeddingRuntimeConfig();
    const qdrant = new QdrantClient({ url: config.qdrantUrl });
    const ripgrepAvailable = await hasRipgrep();
    const qdrantStatus = await checkQdrantConnection(qdrant);
    const repositories = await listIndexedRepositories(config);
    return {
        cwd: process.cwd(),
        qdrantUrl: config.qdrantUrl,
        qdrantCollection: config.qdrantCollection,
        embedding,
        qdrantReachable: qdrantStatus.ok,
        qdrantMessage: qdrantStatus.message,
        ripgrepAvailable,
        ripgrepMessage: ripgrepAvailable ? "ripgrep available" : "ripgrep is not installed",
        indexRoot: config.indexRoot,
        repositoriesRoot: config.repositoriesRoot,
        registryPath: config.registryPath,
        legacyLocalLexicalIndexPath: config.localLexicalIndexPath,
        repositoryCount: repositories.length,
        repositories: await Promise.all(repositories.map(async (repository) => {
            const manifest = await readRepoManifest(repository.manifestPath);
            return {
                repoId: repository.repoId,
                repoName: repository.repoName,
                repoRoot: repository.repoRoot,
                indexedAt: repository.indexedAt,
                fileCount: repository.fileCount,
                coverage: manifest?.coverage,
                freshnessStrategy: manifest?.freshnessStrategy,
                semanticIndex: manifest?.semanticIndex,
            };
        })),
        repoHint: path.resolve(process.env.REPO_ROOT || "."),
    };
}
