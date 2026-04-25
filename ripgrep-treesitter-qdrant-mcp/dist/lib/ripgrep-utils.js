import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { getWindowsReservedDeviceExcludeGlobs } from "./windows-path-utils.js";
const execFileAsync = promisify(execFile);
function getRipgrepCaseArgs(caseMode) {
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
function parseRipgrepJson(stdout, metadata = {}) {
    const matches = [];
    for (const line of stdout.split(/\r?\n/)) {
        const trimmed = line.trim();
        if (!trimmed) {
            continue;
        }
        let event;
        try {
            event = JSON.parse(trimmed);
        }
        catch {
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
export async function hasRipgrep() {
    try {
        await execFileAsync("rg", ["--version"]);
        return true;
    }
    catch {
        return false;
    }
}
export async function queryRipgrep(repoRoot, query, limit, metadata = {}, caseMode = "smart") {
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
    }
    catch (error) {
        if (error?.code === 1) {
            return parseRipgrepJson(error?.stdout || "", metadata).slice(0, Math.max(1, limit));
        }
        throw new Error(error?.stderr || error?.message || "ripgrep search failed");
    }
}
