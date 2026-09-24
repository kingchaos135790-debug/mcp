import path from "node:path";
import { clampLimit, getSearchEngineConfig } from "./config.js";
import { listIndexedRepositories, readRepoManifest, resolveRepository } from "./repository-store.js";
import { queryGitNexus, gitNexusHealth } from "../lib/gitnexus-utils.js";
import { readLocalLexicalIndex, searchLocalLexicalDocuments } from "../lib/local-lexical-utils.js";
import { hasRipgrep, queryRipgrep } from "../lib/ripgrep-utils.js";
const HYBRID_RRF_K = parsePositiveNumber(process.env.HYBRID_RRF_K, 60);
const HYBRID_GITNEXUS_WEIGHT = parsePositiveNumber(process.env.HYBRID_GITNEXUS_WEIGHT, 1.2);
const HYBRID_LEXICAL_WEIGHT = parsePositiveNumber(process.env.HYBRID_LEXICAL_WEIGHT, 1.2);
function parsePositiveNumber(value, fallback) {
    const parsed = Number(value);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}
function normalizeResultPath(result) {
    return String(result.filePath || result.path || result.file || "")
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
export function fuseResults(gitnexus, lexical, limit = 8) {
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
        else if (source === "gitnexus") {
            candidate.result = mergeResultFields(result, candidate.result);
        }
        else {
            candidate.result = mergeResultFields(candidate.result, result);
        }
        if (candidate.sources.has(source))
            return;
        candidate.score += reciprocalRank(rank, weight);
        candidate.sources.add(source);
        if (source === "gitnexus") {
            candidate.gitnexusRank = Math.min(candidate.gitnexusRank ?? rank, rank);
        }
        else {
            candidate.lexicalRank = Math.min(candidate.lexicalRank ?? rank, rank);
        }
    };
    gitnexus.forEach((result, index) => addResult(result, "gitnexus", index + 1, HYBRID_GITNEXUS_WEIGHT));
    lexical.forEach((result, index) => addResult(result, "lexical", index + 1, HYBRID_LEXICAL_WEIGHT));
    const maxScore = (HYBRID_GITNEXUS_WEIGHT + HYBRID_LEXICAL_WEIGHT) / (HYBRID_RRF_K + 1);
    return candidates
        .sort((a, b) => b.score - a.score
        || (a.gitnexusRank ?? Number.MAX_SAFE_INTEGER) - (b.gitnexusRank ?? Number.MAX_SAFE_INTEGER)
        || (a.lexicalRank ?? Number.MAX_SAFE_INTEGER) - (b.lexicalRank ?? Number.MAX_SAFE_INTEGER))
        .slice(0, Math.max(1, limit))
        .map((candidate) => ({
        ...candidate.result,
        source: candidate.sources.size > 1 ? "hybrid" : Array.from(candidate.sources)[0],
        sources: Array.from(candidate.sources),
        fusionScore: Number((candidate.score / maxScore).toFixed(6)),
        gitnexusRank: candidate.gitnexusRank,
        lexicalRank: candidate.lexicalRank,
    }));
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
export async function lexicalCodeSearch(query, limit, repo, caseMode) {
    const cappedLimit = clampLimit(limit);
    return resolveLexicalSearch(String(query), cappedLimit, repo, normalizeCaseMode(caseMode));
}
export async function hybridCodeSearch(query, limit, repo) {
    const config = getSearchEngineConfig();
    const cappedLimit = clampLimit(limit, 8, 50);
    const repository = await resolveRepository(config, repo);
    const repositories = repository ? [repository] : await listIndexedRepositories(config);
    const lexical = await resolveLexicalSearch(String(query), cappedLimit, repo);
    const graphHits = [];
    const warnings = [...(lexical.status.warnings || [])];
    const graphStatus = [];
    // Bound native database concurrency and interleave repositories before fusion.
    for (const target of repositories) {
        try {
            const graph = await queryGitNexus(target, String(query), cappedLimit);
            graphHits.push(graph.hits);
            if (graph.warning)
                warnings.push(`${target.repoName}: ${graph.warning}`);
            graphStatus.push({ repoId: target.repoId, available: true, degraded: Boolean(graph.warning) });
        }
        catch (error) {
            graphStatus.push({ repoId: target.repoId, available: false, message: error.message });
            warnings.push(`${target.repoName}: ${error.message}. Keyword search remains available; re-run index_repository if the graph is missing or stale.`);
        }
    }
    const gitnexus = [];
    for (let rank = 0; rank < cappedLimit; rank += 1) {
        for (const hits of graphHits)
            if (hits[rank])
                gitnexus.push(hits[rank]);
    }
    return {
        gitnexus: gitnexus.slice(0, cappedLimit),
        lexical: lexical.hits,
        fused: fuseResults(gitnexus, lexical.hits, cappedLimit),
        status: {
            ...lexical.status,
            searchBackend: "gitnexus+lexical",
            gitnexus: graphStatus,
            embeddings: false,
            repoFilter: repository?.repoId,
            lexicalBackend: lexical.backend,
            fusion: {
                algorithm: "weighted_rrf",
                rrfK: HYBRID_RRF_K,
                gitnexusWeight: HYBRID_GITNEXUS_WEIGHT,
                lexicalWeight: HYBRID_LEXICAL_WEIGHT,
            },
            warnings,
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
            gitnexusIndex: manifest?.gitnexusIndex,
        };
    }));
}
export async function searchEngineHealth() {
    const config = getSearchEngineConfig();
    const gitnexus = await gitNexusHealth();
    const ripgrepAvailable = await hasRipgrep();
    const repositories = await listIndexedRepositories(config);
    return {
        cwd: process.cwd(),
        searchBackend: "gitnexus+lexical",
        gitnexus,
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
                gitnexusIndex: manifest?.gitnexusIndex,
            };
        })),
        repoHint: path.resolve(process.env.REPO_ROOT || "."),
    };
}
