import { execFile } from "node:child_process";
import fs from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { getSearchEngineConfig } from "../core/config.js";
const execFileAsync = promisify(execFile);
const engineRoot = fileURLToPath(new URL("../../", import.meta.url));
export function gitNexusRuntime() {
    const { indexRoot } = getSearchEngineConfig();
    const searchPath = Object.entries(process.env).find(([key]) => key.toLowerCase() === "path")?.[1] || "";
    const directories = searchPath.split(path.delimiter).filter(Boolean);
    const dllCandidates = [process.env.GITNEXUS_DLL_DIR || "", ...directories.map(directory => path.resolve(directory, "../mingw64/bin")), ...directories];
    const dllDirectory = process.platform === "win32" ? dllCandidates.find(directory => directory
        && existsSync(path.join(directory, "libcrypto-3-x64.dll"))
        && existsSync(path.join(directory, "libssl-3-x64.dll"))) : undefined;
    return {
        node: process.env.GITNEXUS_NODE_EXE || path.join(engineRoot, "node_modules/node/bin", process.platform === "win32" ? "node.exe" : "node"),
        cli: process.env.GITNEXUS_CLI_PATH || path.join(engineRoot, "node_modules/gitnexus/dist/cli/index.js"),
        home: path.join(indexRoot, "gitnexus", "home"),
        storageRoot: path.join(indexRoot, "gitnexus", "repositories"),
        identityCache: path.join(indexRoot, "gitnexus", "analyzer-cache"),
        dllDirectory,
    };
}
export async function runGitNexus(args, timeout = 120_000) {
    const runtime = gitNexusRuntime();
    if (args[0] === "analyze")
        await fs.mkdir(runtime.identityCache, { recursive: true });
    const env = { ...process.env };
    if (runtime.dllDirectory) {
        const pathKey = Object.keys(env).find(key => key.toLowerCase() === "path") || "PATH";
        const currentPath = env[pathKey] || "";
        for (const key of Object.keys(env))
            if (key.toLowerCase() === "path")
                delete env[key];
        env.PATH = `${runtime.dllDirectory}${path.delimiter}${currentPath}`;
    }
    try {
        const nodeArgs = args[0] === "analyze" ? ["--max-old-space-size=8192", "--stack-size=4096"] : [];
        const { stdout } = await execFileAsync(runtime.node, [...nodeArgs, runtime.cli, ...args], {
            cwd: engineRoot,
            windowsHide: true,
            timeout,
            maxBuffer: 32 * 1024 * 1024,
            env: {
                ...env,
                GITNEXUS_HOME: runtime.home,
                GITNEXUS_STORAGE_ROOT: runtime.storageRoot,
                // Always use isolated per-repository storage, even if the caller has a global override.
                GITNEXUS_STORAGE_PATH: undefined,
                GITNEXUS_ANALYZER_IDENTITY_CACHE_DIR: runtime.identityCache,
                GITNEXUS_LBUG_EXTENSION_INSTALL: process.env.GITNEXUS_LBUG_EXTENSION_INSTALL || (args[0] === "analyze" ? "auto" : "load-only"),
                // Avoid GitNexus's adaptive small-pool estimate exhausting COPY memory on Windows.
                GITNEXUS_LBUG_BUFFER_POOL_SIZE: process.env.GITNEXUS_LBUG_BUFFER_POOL_SIZE || "2147483648",
                NO_COLOR: "1",
            },
        });
        return stdout;
    }
    catch (error) {
        const output = String(error.stderr || error.stdout || error.message).trim();
        const detail = output.length > 2500 ? `${output.slice(0, 1500)}\n...\n${output.slice(-1000)}` : output;
        throw new Error(`GitNexus ${args[0]} failed${error.killed ? " (timeout)" : ""}: ${detail}`);
    }
}
export function parseGitNexusJson(output) {
    const text = output.trim();
    // CLI startup diagnostics may precede the JSON. Reject empty or malformed output.
    for (let index = 0; index < text.length; index += 1) {
        if (text[index] !== "{" && text[index] !== "[")
            continue;
        try {
            return JSON.parse(text.slice(index));
        }
        catch { /* try the next JSON boundary */ }
    }
    throw new Error("GitNexus returned invalid or empty JSON");
}
export function normalizeGitNexusResults(result, repository, limit) {
    if (!result || result.error || result.partial)
        throw new Error(String(result?.error || "GitNexus returned partial results"));
    if (!Array.isArray(result.process_symbols) || !Array.isArray(result.definitions)) {
        throw new Error("Unrecognized GitNexus query response");
    }
    const processes = new Map((result.processes || []).map((item) => [item.id, item]));
    const hits = new Map();
    for (const symbol of [...result.process_symbols, ...result.definitions]) {
        const filePath = symbol.filePath || symbol.file_path;
        if (!filePath)
            continue;
        const key = symbol.id || `${filePath}:${symbol.startLine}:${symbol.name}`;
        const process = processes.get(symbol.process_id);
        const existing = hits.get(key);
        const flow = process ? { id: process.id, label: process.summary, type: process.process_type } : undefined;
        if (existing) {
            if (flow && !existing.processes.some((item) => item.id === flow.id))
                existing.processes.push(flow);
            continue;
        }
        hits.set(key, {
            repoId: repository.repoId,
            repoName: repository.repoName,
            repoRoot: repository.repoRoot,
            path: filePath,
            filePath,
            symbol: symbol.name,
            kind: symbol.type,
            startLine: symbol.startLine,
            endLine: symbol.endLine,
            content: symbol.content || "",
            symbolId: symbol.id,
            module: symbol.module,
            processes: flow ? [flow] : [],
            source: "gitnexus",
            backend: "gitnexus",
        });
    }
    return [...hits.values()].slice(0, limit);
}
export async function queryGitNexus(repository, query, limit) {
    const output = await runGitNexus(["query", "--repo", repository.repoRoot, "--limit", String(limit), "--content", "--", query], 45_000);
    const result = parseGitNexusJson(output);
    return { hits: normalizeGitNexusResults(result, repository, limit), warning: result.warning };
}
async function readGraphMetadata(repoId) {
    const runtime = gitNexusRuntime();
    const registry = JSON.parse(await fs.readFile(path.join(runtime.home, "registry.json"), "utf8"));
    const entry = Array.isArray(registry) ? registry.find((item) => item.name === repoId) : undefined;
    if (!entry?.storagePath)
        throw new Error(`GitNexus did not register ${repoId}`);
    const relative = path.relative(runtime.storageRoot, path.resolve(entry.storagePath));
    if (!relative || relative.startsWith("..") || path.isAbsolute(relative))
        throw new Error("GitNexus storage escaped the configured index root");
    return JSON.parse(await fs.readFile(path.join(entry.storagePath, "meta.json"), "utf8"));
}
export async function syncGitNexusExcludes(repoRoot, patterns) {
    const filename = path.join(repoRoot, ".gitnexusignore");
    let previous = "";
    try {
        previous = await fs.readFile(filename, "utf8");
    }
    catch (error) {
        if (error.code !== "ENOENT")
            throw error;
    }
    const begin = "# BEGIN windows-code-search-mcp exclusions";
    const end = "# END windows-code-search-mcp exclusions";
    const start = previous.indexOf(begin);
    const finish = previous.indexOf(end);
    if ((start >= 0) !== (finish >= 0) || (start >= 0 && finish < start)) {
        throw new Error("Malformed managed exclusions block in .gitnexusignore; preserve or remove both marker lines.");
    }
    const rules = [...new Set(patterns.map(pattern => pattern.trim()).filter(Boolean))];
    if (rules.some(pattern => /[\r\n]/.test(pattern)))
        throw new Error("Exclude patterns must each be one line");
    const block = rules.length ? `${begin}\n${rules.join("\n")}\n${end}` : "";
    const next = start >= 0
        ? previous.slice(0, start) + block + previous.slice(finish + end.length)
        : block ? `${previous}${previous && !previous.endsWith("\n") ? "\n" : ""}${block}\n` : previous;
    if (next === previous)
        return false;
    await fs.writeFile(filename, next, "utf8");
    return true;
}
export async function analyzeGitNexus(repoRoot, repoId, force, extraExcludeGlobs = []) {
    // GitNexus merges .gitnexusrc defaults into CLI options. Its CLI has no
    // --no-embeddings switch, so reject a config that would re-enable embeddings.
    let config;
    try {
        config = JSON.parse((await fs.readFile(path.join(repoRoot, ".gitnexusrc"), "utf8")).replace(/^\uFEFF/, ""));
    }
    catch (error) {
        if (error.code !== "ENOENT")
            throw error;
    }
    const embeddings = config?.analyze?.embeddings ?? config?.embeddings;
    if (embeddings !== undefined && embeddings !== false) {
        throw new Error("This search engine disables embeddings. Set embeddings=false in .gitnexusrc before indexing.");
    }
    const exclusionsChanged = await syncGitNexusExcludes(repoRoot, extraExcludeGlobs);
    const args = ["analyze", repoRoot, "--name", repoId, "--index-only", "--skip-git", "--drop-embeddings"];
    if (force || exclusionsChanged)
        args.push("--force");
    await runGitNexus(args, 1_800_000);
    let meta = await readGraphMetadata(repoId);
    if (meta.capabilities?.fts?.status !== "available") {
        await runGitNexus([...args.filter(arg => arg !== "--force"), "--repair-fts"], 300_000);
        meta = await readGraphMetadata(repoId);
    }
    if (meta.capabilities?.fts?.status !== "available" || !meta.stats || meta.stats.embeddings !== 0) {
        throw new Error("GitNexus graph is not search-ready: full-text indexes must be available and embeddings must be disabled.");
    }
    return { backend: "gitnexus", repo: repoId, embeddings: false, indexedAt: meta.indexedAt };
}
export async function gitNexusHealth() {
    try {
        return { available: true, version: (await runGitNexus(["--version"], 15_000)).trim(), ...gitNexusRuntime(), embeddings: false };
    }
    catch (error) {
        return { available: false, message: error.message, ...gitNexusRuntime(), embeddings: false };
    }
}
