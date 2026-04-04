import { execFile } from "node:child_process";
import { promisify } from "node:util";

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


