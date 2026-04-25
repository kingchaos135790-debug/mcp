import path from "node:path";
import { QdrantClient } from "@qdrant/js-client-rest";
import { clampLimit, getSearchEngineConfig } from "./config.js";
import { listIndexedRepositories, readRepoManifest, resolveRepository } from "./repository-store.js";
import { checkQdrantConnection, semanticSearch } from "../lib/qdrant-utils.js";
import { readLocalLexicalIndex, searchLocalLexicalDocuments } from "../lib/local-lexical-utils.js";
import { hasRipgrep, queryRipgrep } from "../lib/ripgrep-utils.js";

function formatSemantic(hit: any) {
  return {
    score: hit.score,
    ...(hit.payload || {}),
  };
}

function fuseResults(semantic: any[], lexical: any[]) {
  const seen = new Set<string>();
  const fused: any[] = [];

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

function buildRepoFilter(repoId: string): Record<string, unknown> {
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

type CaseMode = "smart" | "ignore" | "sensitive";

function normalizeCaseMode(caseMode?: string): CaseMode {
  switch (caseMode) {
    case "ignore":
    case "sensitive":
      return caseMode;
    case "smart":
    default:
      return "smart";
  }
}

function uniqueWarnings(values: string[]): string[] {
  return Array.from(new Set(values.filter(Boolean)));
}

function queryLooksLikeDocs(query: string): boolean {
  const normalized = query.toLowerCase();
  return /\b(proposal|readme|docs?|documentation|markdown|mdx)\b/.test(normalized) || normalized.includes(".md");
}

function queryLooksLikeGenerated(query: string): boolean {
  const normalized = query.toLowerCase();
  return /\b(generated|dist|build|coverage|node_modules|bin|obj)\b/.test(normalized) || normalized.includes(".next");
}

async function buildQueryCoverageWarnings(query: string, targetRepositories: any[]): Promise<string[]> {
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

  const warnings: string[] = [];
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

async function resolveLexicalSearch(query: string, limit: number, repo?: string, caseMode: CaseMode = "smart") {
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
    } catch (error: any) {
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

async function resolveLocalLexicalSearch(targetRepositories: any[], repositories: any[], query: string, limit: number) {
  const documents = [];
  const availableRepositories: string[] = [];
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

export async function semanticCodeSearch(query: string, limit?: number, repo?: string) {
  const config = getSearchEngineConfig();
  const qdrant = new QdrantClient({ url: config.qdrantUrl });
  const cappedLimit = clampLimit(limit);
  const repository = await resolveRepository(config, repo);
  const hits = await semanticSearch(
    qdrant,
    config.qdrantCollection,
    String(query),
    cappedLimit,
    repository ? buildRepoFilter(repository.repoId) : undefined,
  );
  return hits.map(formatSemantic);
}

export async function lexicalCodeSearch(query: string, limit?: number, repo?: string, caseMode?: string) {
  const cappedLimit = clampLimit(limit);
  return resolveLexicalSearch(String(query), cappedLimit, repo, normalizeCaseMode(caseMode));
}

export async function hybridCodeSearch(query: string, limit?: number, repo?: string) {
  const config = getSearchEngineConfig();
  const qdrant = new QdrantClient({ url: config.qdrantUrl });
  const cappedLimit = clampLimit(limit);
  const repository = await resolveRepository(config, repo);
  const semantic = await semanticSearch(
    qdrant,
    config.qdrantCollection,
    String(query),
    cappedLimit,
    repository ? buildRepoFilter(repository.repoId) : undefined,
  );
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
    };
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
      };
    })),
    repoHint: path.resolve(process.env.REPO_ROOT || "."),
  };
}



