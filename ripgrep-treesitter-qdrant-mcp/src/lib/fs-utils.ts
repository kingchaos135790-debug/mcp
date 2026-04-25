import fg from "fast-glob";
import fs from "node:fs/promises";
import path from "node:path";

import { getWindowsReservedDeviceExcludeGlobs, isWindowsReservedDevicePath } from "./windows-path-utils.js";

export const DEFAULT_INDEXED_EXTENSIONS = [
  ".ts",
  ".tsx",
  ".js",
  ".jsx",
  ".mjs",
  ".cjs",
  ".py",
  ".go",
  ".rs",
  ".java",
  ".c",
  ".cpp",
  ".h",
  ".hpp",
  ".cs",
  ".rb",
  ".php",
];

export const DEFAULT_DOC_EXTENSIONS = [".md", ".mdx", ".rst", ".adoc", ".txt"];

const DEFAULT_MAX_SOURCE_FILE_BYTES = Number.parseInt(process.env.MAX_SOURCE_FILE_BYTES || "1048576", 10);

const ALWAYS_IGNORED_GLOBS = [
  "**/node_modules/**",
  "**/.git/**",
  "**/vendor/**",
  "**/vendors/**",
  "**/third_party/**",
  "**/third-party/**",
  "**/*.min.js",
];

const GENERATED_IGNORED_GLOBS = [
  "**/dist/**",
  "**/build/**",
  "**/.next/**",
  "**/coverage/**",
  "**/generated/**",
  "**/bin/**",
  "**/obj/**",
];

export const DEFAULT_IGNORED_GLOBS = [
  ...ALWAYS_IGNORED_GLOBS,
  ...GENERATED_IGNORED_GLOBS,
  ...getWindowsReservedDeviceExcludeGlobs(),
];

export type IndexCoverageOptions = {
  includeDocs?: boolean;
  includeGenerated?: boolean;
  extraExtensions?: string[];
  extraIncludeGlobs?: string[];
  extraExcludeGlobs?: string[];
  maxFileBytes?: number;
};

export type EffectiveIndexCoverage = {
  indexedExtensions: string[];
  ignoredGlobs: string[];
  includeDocs: boolean;
  includeGenerated: boolean;
  extraExtensions: string[];
  extraIncludeGlobs: string[];
  extraExcludeGlobs: string[];
  maxFileBytes: number;
};

export type ExcludedFileSummary = {
  unsupportedExtension: number;
  ignoredGlob: number;
  tooLarge: number;
};

export type ExcludedFileSample = {
  path: string;
  reason: string;
};

export type SourceFileDiscoveryReport = {
  files: string[];
  scannedFilesystemEntries: number;
  indexedCandidateFiles: number;
  excludedFiles: ExcludedFileSummary;
  recentExcludedFiles: ExcludedFileSample[];
  coverage: EffectiveIndexCoverage;
};

export function normalizeExtension(extension: string): string {
  const trimmed = String(extension || "").trim().toLowerCase();
  if (!trimmed) return "";
  return trimmed.startsWith(".") ? trimmed : `.${trimmed}`;
}

function uniqueSorted(values: string[]): string[] {
  return Array.from(new Set(values.filter(Boolean))).sort((a, b) => a.localeCompare(b));
}

export function resolveIndexCoverageOptions(options: IndexCoverageOptions = {}): EffectiveIndexCoverage {
  const includeDocs = Boolean(options.includeDocs);
  const includeGenerated = Boolean(options.includeGenerated);
  const extraExtensions = uniqueSorted((options.extraExtensions || []).map(normalizeExtension));
  const indexedExtensions = uniqueSorted([
    ...DEFAULT_INDEXED_EXTENSIONS,
    ...(includeDocs ? DEFAULT_DOC_EXTENSIONS : []),
    ...extraExtensions,
  ]);
  const ignoredGlobs = [
    ...ALWAYS_IGNORED_GLOBS,
    ...(includeGenerated ? [] : GENERATED_IGNORED_GLOBS),
    ...getWindowsReservedDeviceExcludeGlobs(),
    ...(options.extraExcludeGlobs || []),
  ];
  const maxFileBytes = Number.isFinite(options.maxFileBytes) && Number(options.maxFileBytes) > 0
    ? Number(options.maxFileBytes)
    : DEFAULT_MAX_SOURCE_FILE_BYTES;

  return {
    indexedExtensions,
    ignoredGlobs,
    includeDocs,
    includeGenerated,
    extraExtensions,
    extraIncludeGlobs: [...(options.extraIncludeGlobs || [])].sort((a, b) => a.localeCompare(b)),
    extraExcludeGlobs: [...(options.extraExcludeGlobs || [])].sort((a, b) => a.localeCompare(b)),
    maxFileBytes,
  };
}

function globToRegExp(glob: string): RegExp {
  let normalized = glob.trim().replace(/^!/, "").replace(/\\/g, "/");
  if (!normalized) normalized = "**/*";

  let output = "";
  for (let i = 0; i < normalized.length; i += 1) {
    const char = normalized[i];
    const next = normalized[i + 1];
    if (char === "*" && next === "*") {
      const following = normalized[i + 2];
      if (following === "/") {
        output += "(?:.*\/)?";
        i += 2;
      } else {
        output += ".*";
        i += 1;
      }
    } else if (char === "*") {
      output += "[^/]*";
    } else if (char === "?") {
      output += "[^/]";
    } else if ("\\^$+?.()|{}[]".includes(char)) {
      output += `\\${char}`;
    } else {
      output += char;
    }
  }
  return new RegExp(`^${output}$`, "i");
}

function matchesAnyGlob(relativePath: string, globs: string[]): string | undefined {
  const normalizedPath = relativePath.replace(/\\/g, "/");
  for (const glob of globs) {
    if (globToRegExp(glob).test(normalizedPath)) {
      return glob;
    }
  }
  return undefined;
}

function addRecentExcluded(sample: ExcludedFileSample[], item: ExcludedFileSample): void {
  if (sample.length < 25) {
    sample.push(item);
  }
}

export async function discoverSourceFiles(root: string, options: IndexCoverageOptions = {}): Promise<SourceFileDiscoveryReport> {
  const coverage = resolveIndexCoverageOptions(options);
  const allFiles = await fg(["**/*"], {
    cwd: root,
    absolute: true,
    dot: false,
    onlyFiles: true,
    followSymbolicLinks: false,
  });

  const files: string[] = [];
  const excludedFiles: ExcludedFileSummary = {
    unsupportedExtension: 0,
    ignoredGlob: 0,
    tooLarge: 0,
  };
  const recentExcludedFiles: ExcludedFileSample[] = [];

  for (const file of allFiles) {
    const relativePath = toPosixRelative(root, file);
    const ignoredGlob = isWindowsReservedDevicePath(file)
      ? "windowsReservedDeviceName"
      : matchesAnyGlob(relativePath, coverage.ignoredGlobs);
    if (ignoredGlob) {
      excludedFiles.ignoredGlob += 1;
      addRecentExcluded(recentExcludedFiles, { path: relativePath, reason: `ignoredGlob:${ignoredGlob}` });
      continue;
    }

    let stat;
    try {
      stat = await fs.stat(file);
    } catch {
      excludedFiles.ignoredGlob += 1;
      addRecentExcluded(recentExcludedFiles, { path: relativePath, reason: "unreadable" });
      continue;
    }

    if (Number.isFinite(coverage.maxFileBytes) && coverage.maxFileBytes > 0 && stat.size > coverage.maxFileBytes) {
      excludedFiles.tooLarge += 1;
      addRecentExcluded(recentExcludedFiles, { path: relativePath, reason: `tooLarge:${stat.size}` });
      continue;
    }

    const extension = normalizeExtension(path.extname(file));
    const matchedIncludeGlob = matchesAnyGlob(relativePath, coverage.extraIncludeGlobs);
    if (!coverage.indexedExtensions.includes(extension) && !matchedIncludeGlob) {
      excludedFiles.unsupportedExtension += 1;
      addRecentExcluded(recentExcludedFiles, { path: relativePath, reason: `unsupportedExtension:${extension || "<none>"}` });
      continue;
    }

    files.push(file);
  }

  const sortedFiles = files.sort((a, b) => a.localeCompare(b));
  return {
    files: sortedFiles,
    scannedFilesystemEntries: allFiles.length,
    indexedCandidateFiles: sortedFiles.length,
    excludedFiles,
    recentExcludedFiles,
    coverage,
  };
}

export async function listSourceFiles(root: string, options: IndexCoverageOptions = {}): Promise<string[]> {
  return (await discoverSourceFiles(root, options)).files;
}

export async function readText(filePath: string): Promise<string> {
  return fs.readFile(filePath, "utf8");
}

export function toPosixRelative(root: string, filePath: string): string {
  return path.relative(root, filePath).split(path.sep).join("/");
}
