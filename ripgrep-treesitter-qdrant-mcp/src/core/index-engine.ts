import { execFile } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import { QdrantClient } from "@qdrant/js-client-rest";
import { getSearchEngineConfig } from "./config.js";
import {
  getRepoStoragePaths,
  hashText,
  removeIndexedRepository,
  resolveRepository,
  upsertIndexedRepository,
  writeRepoManifest,
  readRepoManifest,
  type RepoIndexManifest,
  type RepoIndexedFileRecord,
} from "./repository-store.js";
import {
  checkQdrantConnection,
  deletePoints,
  deletePointsByFilter,
  ensureCollection,
  fakeEmbedding,
  upsertChunks,
} from "../lib/qdrant-utils.js";
import {
  discoverSourceFiles,
  readText,
  toPosixRelative,
  type EffectiveIndexCoverage,
  type ExcludedFileSample,
  type IndexCoverageOptions,
} from "../lib/fs-utils.js";
import { extractCodeChunks } from "../lib/tree-sitter-utils.js";
import { buildLocalLexicalDocument, writeLocalLexicalIndex } from "../lib/local-lexical-utils.js";
import { hasRipgrep } from "../lib/ripgrep-utils.js";

const execFileAsync = promisify(execFile);

type IndexMode = "incremental" | "force" | "verify";
type HashMode = "metadata-first" | "hash-changed-candidates" | "hash-all-candidates";

export type IndexRepositoryOptions = IndexCoverageOptions & {
  repoRoot?: string;
  repo_root?: string;
  mode?: string;
  hashMode?: string;
};

type GitChangeReport = {
  available: boolean;
  files: string[];
  error?: string;
};

type VerificationReport = {
  manifestPresent: boolean;
  manifestIndexedAt?: string;
  manifestMissingFiles: string[];
  candidateFilesMissingFromManifest: string[];
  recentExcludedFiles: ExcludedFileSample[];
  hashMismatches: string[];
  gitChangedIndexedFiles: string[];
  gitChangedExcludedFiles: Array<{ path: string; reason: string }>;
};

function buildPointId(
  repoId: string,
  relativePath: string,
  chunk: { symbol: string; kind: string; startLine: number; endLine: number; text: string },
): string {
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

function createEmptyManifest(repoId: string, repoName: string, repoRoot: string): RepoIndexManifest {
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

function normalizeIndexMode(mode?: string): IndexMode {
  switch (mode) {
    case "force":
    case "verify":
      return mode;
    case "incremental":
    default:
      return "incremental";
  }
}

function normalizeHashMode(hashMode?: string, mode: IndexMode = "incremental"): HashMode {
  switch (hashMode) {
    case "hash-changed-candidates":
    case "hash-all-candidates":
    case "metadata-first":
      return hashMode;
    default:
      return mode === "force" ? "hash-all-candidates" : "metadata-first";
  }
}

function unique(values: string[]): string[] {
  return Array.from(new Set(values.filter(Boolean)));
}

async function readRepoIndexConfig(repoRoot: string): Promise<IndexCoverageOptions> {
  try {
    const raw = await fs.readFile(path.join(repoRoot, ".mcp-index.json"), "utf8");
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    return {
      includeDocs: typeof parsed.includeDocs === "boolean" ? parsed.includeDocs : undefined,
      includeGenerated: typeof parsed.includeGenerated === "boolean" ? parsed.includeGenerated : undefined,
      maxFileBytes: typeof parsed.maxFileBytes === "number" ? parsed.maxFileBytes : undefined,
      extraExtensions: Array.isArray(parsed.extraExtensions) ? parsed.extraExtensions.map(String) : undefined,
      extraIncludeGlobs: unique([
        ...(Array.isArray(parsed.extraIncludeGlobs) ? parsed.extraIncludeGlobs.map(String) : []),
        ...(Array.isArray(parsed.include) ? parsed.include.map(String) : []),
      ]),
      extraExcludeGlobs: unique([
        ...(Array.isArray(parsed.extraExcludeGlobs) ? parsed.extraExcludeGlobs.map(String) : []),
        ...(Array.isArray(parsed.exclude) ? parsed.exclude.map(String) : []),
      ]),
    };
  } catch {
    return {};
  }
}

function mergeCoverageOptions(configFileOptions: IndexCoverageOptions, callOptions: IndexCoverageOptions): IndexCoverageOptions {
  return {
    includeDocs: callOptions.includeDocs ?? configFileOptions.includeDocs,
    includeGenerated: callOptions.includeGenerated ?? configFileOptions.includeGenerated,
    maxFileBytes: callOptions.maxFileBytes ?? configFileOptions.maxFileBytes,
    extraExtensions: unique([
      ...(configFileOptions.extraExtensions || []),
      ...(callOptions.extraExtensions || []),
    ]),
    extraIncludeGlobs: unique([
      ...(configFileOptions.extraIncludeGlobs || []),
      ...(callOptions.extraIncludeGlobs || []),
    ]),
    extraExcludeGlobs: unique([
      ...(configFileOptions.extraExcludeGlobs || []),
      ...(callOptions.extraExcludeGlobs || []),
    ]),
  };
}

async function getGitChangedFiles(repoRoot: string): Promise<GitChangeReport> {
  try {
    await fs.stat(path.join(repoRoot, ".git"));
  } catch {
    return { available: false, files: [] };
  }

  try {
    const { stdout } = await execFileAsync("git", ["ls-files", "-m", "-o", "--exclude-standard"], {
      cwd: repoRoot,
      maxBuffer: 4 * 1024 * 1024,
    });
    return {
      available: true,
      files: stdout
        .split(/\r?\n/)
        .map((line) => line.trim().replace(/\\/g, "/"))
        .filter(Boolean),
    };
  } catch (error: any) {
    return {
      available: true,
      files: [],
      error: error?.stderr || error?.message || "git change detection failed",
    };
  }
}

function buildWarnings(args: {
  mode: IndexMode;
  hashMode: HashMode;
  changedFiles: number;
  deletedFiles: number;
  coverage: EffectiveIndexCoverage;
  excludedFiles: { unsupportedExtension: number; ignoredGlob: number; tooLarge: number };
  git?: GitChangeReport;
  verification?: VerificationReport;
}): string[] {
  const warnings: string[] = [];

  if (args.mode === "incremental" && args.changedFiles === 0 && args.deletedFiles === 0) {
    warnings.push(
      "No indexed source files changed. This does not mean no repository files changed. Docs, generated files, build outputs, and unsupported extensions may be excluded. Use mode=verify or mode=force to confirm freshness.",
    );
  }

  if (!args.coverage.includeDocs && args.excludedFiles.unsupportedExtension > 0) {
    warnings.push("Documentation files may be excluded by current index coverage. Run with includeDocs=true or add relevant extraExtensions to index them.");
  }

  if (!args.coverage.includeGenerated && args.excludedFiles.ignoredGlob > 0) {
    warnings.push("Generated, build, dependency, or ignored paths may be excluded by current index coverage.");
  }

  if (args.hashMode === "metadata-first") {
    warnings.push("Freshness uses metadata-first detection; same-size same-mtime content changes can be missed. Use hashMode=hash-all-candidates to verify content hashes.");
  }

  if (args.git?.error) {
    warnings.push(`Git-assisted change detection was unavailable: ${args.git.error}`);
  }

  if (args.verification?.hashMismatches.length) {
    warnings.push("Index may be stale; verification found hash mismatches.");
  }

  if (args.mode === "force") {
    warnings.push("Index was force rebuilt for all candidate files.");
  }

  return unique(warnings);
}

async function buildVerificationReport(args: {
  repoRoot: string;
  previousManifest: RepoIndexManifest | null;
  candidateFiles: string[];
  candidateRelativePaths: Set<string>;
  recentExcludedFiles: ExcludedFileSample[];
  hashMode: HashMode;
  git: GitChangeReport;
}): Promise<VerificationReport> {
  const previousFiles = args.previousManifest?.files || {};
  const manifestMissingFiles: string[] = [];
  const candidateFilesMissingFromManifest: string[] = [];
  const hashMismatches: string[] = [];

  for (const relativePath of Object.keys(previousFiles)) {
    try {
      await fs.stat(path.join(args.repoRoot, relativePath));
    } catch {
      manifestMissingFiles.push(relativePath);
    }
  }

  for (const file of args.candidateFiles) {
    const relativePath = toPosixRelative(args.repoRoot, file);
    const existing = previousFiles[relativePath];
    if (!existing) {
      candidateFilesMissingFromManifest.push(relativePath);
      continue;
    }

    if (args.hashMode === "hash-all-candidates") {
      const source = await readText(file);
      const contentHash = hashText(source);
      if (existing.hash !== contentHash) {
        hashMismatches.push(relativePath);
      }
    }
  }

  const gitChangedIndexedFiles: string[] = [];
  const gitChangedExcludedFiles: Array<{ path: string; reason: string }> = [];
  for (const gitPath of args.git.files) {
    if (args.candidateRelativePaths.has(gitPath)) {
      gitChangedIndexedFiles.push(gitPath);
    } else {
      const recentMatch = args.recentExcludedFiles.find((item) => item.path === gitPath);
      gitChangedExcludedFiles.push({
        path: gitPath,
        reason: recentMatch?.reason || "outsideIndexCoverage",
      });
    }
  }

  return {
    manifestPresent: Boolean(args.previousManifest),
    manifestIndexedAt: args.previousManifest?.indexedAt,
    manifestMissingFiles: manifestMissingFiles.sort((a, b) => a.localeCompare(b)),
    candidateFilesMissingFromManifest: candidateFilesMissingFromManifest.sort((a, b) => a.localeCompare(b)),
    recentExcludedFiles: args.recentExcludedFiles,
    hashMismatches: hashMismatches.sort((a, b) => a.localeCompare(b)),
    gitChangedIndexedFiles: gitChangedIndexedFiles.sort((a, b) => a.localeCompare(b)),
    gitChangedExcludedFiles: gitChangedExcludedFiles.sort((a, b) => a.path.localeCompare(b.path)),
  };
}

async function indexOneFile(args: {
  file: string;
  repoRoot: string;
  repoId: string;
  repoName: string;
  indexedAt: string;
  existing?: RepoIndexedFileRecord;
  pointIdsToDelete: Set<string>;
  pointsToUpsert: Array<{ id: string; vector: number[]; payload: any }>;
}): Promise<RepoIndexedFileRecord> {
  const relativePath = toPosixRelative(args.repoRoot, args.file);
  for (const pointId of args.existing?.qdrantPointIds || []) {
    args.pointIdsToDelete.add(pointId);
  }

  const source = await readText(args.file);
  const stat = await fs.stat(args.file);
  const contentHash = hashText(source);
  const chunks = extractCodeChunks(args.file, source);
  const qdrantPointIds: string[] = [];

  for (const chunk of chunks) {
    const id = buildPointId(args.repoId, relativePath, chunk);
    qdrantPointIds.push(id);
    args.pointsToUpsert.push({
      id,
      vector: fakeEmbedding(`${relativePath}\n${chunk.symbol}\n${chunk.text}`),
      payload: {
        repoId: args.repoId,
        repo: args.repoName,
        repoRoot: args.repoRoot,
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

  return {
    path: relativePath,
    hash: contentHash,
    size: stat.size,
    mtimeMs: stat.mtimeMs,
    qdrantPointIds,
    document: buildLocalLexicalDocument(args.repoRoot, args.file, source, {
      repoId: args.repoId,
      repoName: args.repoName,
    }),
    updatedAt: args.indexedAt,
  };
}

export async function indexRepository(repoRootInput?: string, options: IndexRepositoryOptions = {}) {
  const config = getSearchEngineConfig();
  const repoRoot = path.resolve(repoRootInput || options.repoRoot || options.repo_root || process.env.REPO_ROOT || ".");
  const mode = normalizeIndexMode(options.mode);
  const hashMode = normalizeHashMode(options.hashMode, mode);
  const storage = getRepoStoragePaths(config, repoRoot);
  const indexedAt = new Date().toISOString();

  await fs.mkdir(storage.repoDir, { recursive: true });

  const repoConfig = await readRepoIndexConfig(repoRoot);
  const coverageOptions = mergeCoverageOptions(repoConfig, options);
  const discovery = await discoverSourceFiles(repoRoot, coverageOptions);
  const previousManifest = await readRepoManifest(storage.manifestPath);
  const manifest = previousManifest ?? createEmptyManifest(storage.repoId, storage.repoName, storage.repoRoot);
  const git = await getGitChangedFiles(repoRoot);
  const files = discovery.files;
  const candidateRelativePaths = new Set(files.map((file) => toPosixRelative(repoRoot, file)));

  if (mode === "verify") {
    const verification = await buildVerificationReport({
      repoRoot,
      previousManifest,
      candidateFiles: files,
      candidateRelativePaths,
      recentExcludedFiles: discovery.recentExcludedFiles,
      hashMode,
      git,
    });
    return {
      repoId: storage.repoId,
      repoName: storage.repoName,
      repoRoot: storage.repoRoot,
      mode,
      status: "ok",
      manifestPath: storage.manifestPath,
      scannedFilesystemEntries: discovery.scannedFilesystemEntries,
      indexedCandidateFiles: discovery.indexedCandidateFiles,
      changedIndexedFiles: 0,
      unchangedIndexedFiles: files.length,
      deletedIndexedFiles: verification.manifestMissingFiles.length,
      excludedFiles: discovery.excludedFiles,
      coverage: discovery.coverage,
      freshnessStrategy: hashMode,
      verification,
      git: {
        available: git.available,
        changedFiles: git.files.length,
        error: git.error,
      },
      warnings: buildWarnings({
        mode,
        hashMode,
        changedFiles: 0,
        deletedFiles: verification.manifestMissingFiles.length,
        coverage: discovery.coverage,
        excludedFiles: discovery.excludedFiles,
        git,
        verification,
      }),
    };
  }

  const client = new QdrantClient({ url: config.qdrantUrl });
  const qdrantStatus = await checkQdrantConnection(client);
  if (!qdrantStatus.ok) {
    throw new Error(`Qdrant is not reachable at ${config.qdrantUrl}. ${qdrantStatus.message}`);
  }

  await ensureCollection(client, config.qdrantCollection);

  const seenPaths = new Set<string>();
  const nextFiles: Record<string, RepoIndexedFileRecord> = {};
  const pointsToUpsert: Array<{ id: string; vector: number[]; payload: any }> = [];
  const pointIdsToDelete = new Set<string>();

  let changedFiles = 0;
  let unchangedFiles = 0;

  for (const file of files) {
    const relativePath = toPosixRelative(repoRoot, file);
    seenPaths.add(relativePath);

    const stat = await fs.stat(file);
    const existing = manifest.files[relativePath];
    const existingDocument = existing?.document
      ? {
          ...existing.document,
          repoId: storage.repoId,
          repoName: storage.repoName,
        }
      : undefined;

    const forceRebuild = mode === "force";
    const mustHash = forceRebuild || hashMode === "hash-all-candidates";
    const metadataMatches = existing && existing.size === stat.size && existing.mtimeMs === stat.mtimeMs && existingDocument;

    if (!forceRebuild && metadataMatches && !mustHash) {
      nextFiles[relativePath] = {
        ...existing,
        document: existingDocument,
      };
      unchangedFiles += 1;
      continue;
    }

    if (!forceRebuild && existing && existingDocument) {
      const shouldReadAndHash = mustHash || !metadataMatches || hashMode === "hash-changed-candidates";
      if (shouldReadAndHash) {
        const source = await readText(file);
        const contentHash = hashText(source);
        if (existing.hash === contentHash) {
          nextFiles[relativePath] = {
            ...existing,
            size: stat.size,
            mtimeMs: stat.mtimeMs,
            document: existingDocument,
          };
          unchangedFiles += 1;
          continue;
        }
      }
    }

    changedFiles += 1;
    nextFiles[relativePath] = await indexOneFile({
      file,
      repoRoot,
      repoId: storage.repoId,
      repoName: storage.repoName,
      indexedAt,
      existing,
      pointIdsToDelete,
      pointsToUpsert,
    });
  }

  let deletedFiles = 0;
  for (const [relativePath, record] of Object.entries(manifest.files)) {
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

  const nextManifest: RepoIndexManifest = {
    version: 1,
    repoId: storage.repoId,
    repoName: storage.repoName,
    repoRoot: storage.repoRoot,
    indexedAt,
    fileCount: documents.length,
    coverage: discovery.coverage,
    freshnessStrategy: hashMode,
    files: nextFiles,
  };
  await writeRepoManifest(storage.manifestPath, nextManifest);
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
  const warnings = buildWarnings({
    mode,
    hashMode,
    changedFiles,
    deletedFiles,
    coverage: discovery.coverage,
    excludedFiles: discovery.excludedFiles,
    git,
  });

  return {
    repoId: storage.repoId,
    repoName: storage.repoName,
    repoRoot: storage.repoRoot,
    mode,
    status: "ok",
    manifestPath: storage.manifestPath,
    scannedFilesystemEntries: discovery.scannedFilesystemEntries,
    indexedCandidateFiles: discovery.indexedCandidateFiles,
    changedIndexedFiles: changedFiles,
    unchangedIndexedFiles: unchangedFiles,
    deletedIndexedFiles: deletedFiles,
    indexedFiles: files.length,
    changedFiles,
    unchangedFiles,
    deletedFiles,
    excludedFiles: discovery.excludedFiles,
    coverage: discovery.coverage,
    freshnessStrategy: hashMode,
    warnings,
    git: {
      available: git.available,
      changedFiles: git.files.length,
      error: git.error,
    },
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

export async function removeIndexedRepositoryData(reference?: string) {
  const config = getSearchEngineConfig();
  const normalizedReference = String(reference || process.env.REPO_ROOT || ".").trim();
  const resolvedReference = path.resolve(normalizedReference);

  let indexedRepository;
  try {
    indexedRepository = await resolveRepository(config, normalizedReference);
  } catch {
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
