import { execFile } from "node:child_process";
import { promisify } from "node:util";

import { ALWAYS_IGNORED_GLOBS, DEFAULT_IGNORED_GLOBS, DEFAULT_INDEXED_EXTENSIONS } from "./fs-utils.js";
import { getWindowsReservedDeviceExcludeGlobs } from "./windows-path-utils.js";

const execFileAsync = promisify(execFile);

export type RipgrepMatch = {
  repoId?: string;
  repoName?: string;
  file: string;
  line?: number;
  text?: string;
  backend: "ripgrep";
};

type RipgrepJsonEvent = {
  type?: string;
  data?: {
    path?: { text?: string };
    lines?: { text?: string };
    line_number?: number;
  };
};

export type RipgrepCaseMode = "smart" | "ignore" | "sensitive";

export type RipgrepSearchCoverage = {
  indexedExtensions?: string[];
  ignoredGlobs?: string[];
  extraIncludeGlobs?: string[];
  maxFileBytes?: number;
};

function getRipgrepCaseArgs(caseMode: RipgrepCaseMode): string[] {
  switch (caseMode) {
    case "ignore":
      return ["-i"];
    case "sensitive":
      return ["-s"];
    case "smart":
    default:
      return ["--smart-case"];
  }
}

function parseRipgrepJson(stdout: string, metadata: { repoId?: string; repoName?: string } = {}): RipgrepMatch[] {
  const matches: RipgrepMatch[] = [];

  for (const line of stdout.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed) {
      continue;
    }

    let event: RipgrepJsonEvent;
    try {
      event = JSON.parse(trimmed) as RipgrepJsonEvent;
    } catch {
      continue;
    }

    if (event.type !== "match") {
      continue;
    }

    matches.push({
      repoId: metadata.repoId,
      repoName: metadata.repoName,
      file: event.data?.path?.text || "unknown",
      line: event.data?.line_number,
      text: event.data?.lines?.text?.trim(),
      backend: "ripgrep",
    });
  }

  return matches;
}

function unique(values: string[]): string[] {
  return Array.from(new Set(values.filter(Boolean)));
}

export function buildRipgrepCoverageArgs(coverage: RipgrepSearchCoverage = {}): string[] {
  const indexedExtensions = coverage.indexedExtensions ?? DEFAULT_INDEXED_EXTENSIONS;
  const includeGlobs = unique([
    ...indexedExtensions.map((extension) => {
      const normalized = String(extension || "").trim().toLowerCase();
      if (!normalized) return "";
      return `**/*${normalized.startsWith(".") ? normalized : `.${normalized}`}`;
    }),
    ...(coverage.extraIncludeGlobs || []),
  ]);
  const ignoredGlobs = coverage.ignoredGlobs === undefined
    ? DEFAULT_IGNORED_GLOBS
    : unique([...ALWAYS_IGNORED_GLOBS, ...coverage.ignoredGlobs]);

  const args = [
    ...includeGlobs.flatMap((glob) => ["--glob", glob]),
    ...ignoredGlobs.flatMap((glob) => ["--glob", `!${glob.replace(/^!/, "")}`]),
  ];

  if (Number.isFinite(coverage.maxFileBytes) && Number(coverage.maxFileBytes) > 0) {
    args.push("--max-filesize", String(Math.floor(Number(coverage.maxFileBytes))));
  }
  return args;
}

export async function hasRipgrep(): Promise<boolean> {
  try {
    await execFileAsync("rg", ["--version"]);
    return true;
  } catch {
    return false;
  }
}

export async function queryRipgrep(
  repoRoot: string,
  query: string,
  limit: number,
  metadata: { repoId?: string; repoName?: string } = {},
  caseMode: RipgrepCaseMode = "smart",
  coverage: RipgrepSearchCoverage = {},
): Promise<RipgrepMatch[]> {
  const reservedDeviceExcludeGlobs = getWindowsReservedDeviceExcludeGlobs();
  const args = [
    "--json",
    "--line-number",
    "--color",
    "never",
    ...getRipgrepCaseArgs(caseMode),
    "--hidden",
    "--glob",
    "!.git",
    ...buildRipgrepCoverageArgs(coverage),
    ...reservedDeviceExcludeGlobs.flatMap((glob) => ["--glob", glob]),
    "--max-count",
    String(Math.max(1, limit)),
    "--",
    query,
    ".",
  ];

  try {
    const { stdout } = await execFileAsync("rg", args, { cwd: repoRoot, maxBuffer: 8 * 1024 * 1024 });
    return parseRipgrepJson(stdout, metadata).slice(0, Math.max(1, limit));
  } catch (error: any) {
    if (error?.code === 1) {
      return parseRipgrepJson(error?.stdout || "", metadata).slice(0, Math.max(1, limit));
    }
    throw new Error(error?.stderr || error?.message || "ripgrep search failed");
  }
}


