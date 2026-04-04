import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
export function hashText(value) {
    return crypto.createHash("sha1").update(value).digest("hex");
}
function slugifyRepoName(value) {
    const slug = value.toLowerCase().replace(/[^a-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "");
    return slug || "repo";
}
export function deriveRepoIdentity(repoRoot) {
    const normalizedRoot = path.resolve(repoRoot);
    const repoName = path.basename(normalizedRoot) || "repo";
    const repoId = `${slugifyRepoName(repoName)}-${hashText(normalizedRoot).slice(0, 12)}`;
    return { repoId, repoName };
}
export function getRepoStoragePaths(config, repoRoot) {
    const normalizedRoot = path.resolve(repoRoot);
    const { repoId, repoName } = deriveRepoIdentity(normalizedRoot);
    const repoDir = path.join(config.repositoriesRoot, repoId);
    return {
        repoId,
        repoName,
        repoRoot: normalizedRoot,
        repoDir,
        manifestPath: path.join(repoDir, "manifest.json"),
        localLexicalIndexPath: path.join(repoDir, "local-lexical-index.json"),
        zoektIndexRoot: path.join(repoDir, "zoekt"),
    };
}
async function readJsonFile(filePath) {
    try {
        const raw = await fs.readFile(filePath, "utf8");
        return JSON.parse(raw);
    }
    catch {
        return null;
    }
}
async function writeJsonFile(filePath, payload) {
    await fs.mkdir(path.dirname(filePath), { recursive: true });
    await fs.writeFile(filePath, JSON.stringify(payload, null, 2), "utf8");
}
export async function readRepoManifest(manifestPath) {
    return readJsonFile(manifestPath);
}
export async function writeRepoManifest(manifestPath, manifest) {
    await writeJsonFile(manifestPath, manifest);
}
async function readRepositoryRegistry(config) {
    const registry = await readJsonFile(config.registryPath);
    if (!registry || !Array.isArray(registry.repositories)) {
        return { version: 1, repositories: [] };
    }
    return {
        version: 1,
        repositories: registry.repositories,
    };
}
async function writeRepositoryRegistry(config, repositories) {
    const unique = new Map();
    for (const repository of repositories) {
        unique.set(repository.repoId, repository);
    }
    await writeJsonFile(config.registryPath, {
        version: 1,
        repositories: Array.from(unique.values()).sort((a, b) => a.repoName.localeCompare(b.repoName) || a.repoId.localeCompare(b.repoId)),
    });
}
async function scanRepositoriesFromDisk(config) {
    try {
        const entries = await fs.readdir(config.repositoriesRoot, { withFileTypes: true });
        const repositories = [];
        for (const entry of entries) {
            if (!entry.isDirectory())
                continue;
            const manifestPath = path.join(config.repositoriesRoot, entry.name, "manifest.json");
            const manifest = await readRepoManifest(manifestPath);
            if (!manifest)
                continue;
            repositories.push({
                repoId: manifest.repoId,
                repoName: manifest.repoName,
                repoRoot: manifest.repoRoot,
                indexedAt: manifest.indexedAt,
                fileCount: manifest.fileCount,
                manifestPath,
                localLexicalIndexPath: path.join(config.repositoriesRoot, entry.name, "local-lexical-index.json"),
                zoektIndexRoot: path.join(config.repositoriesRoot, entry.name, "zoekt"),
            });
        }
        return repositories;
    }
    catch {
        return [];
    }
}
export async function listIndexedRepositories(config) {
    const registry = await readRepositoryRegistry(config);
    const repositories = registry.repositories.length ? registry.repositories : await scanRepositoriesFromDisk(config);
    return repositories.sort((a, b) => a.repoName.localeCompare(b.repoName) || a.repoId.localeCompare(b.repoId));
}
export async function upsertIndexedRepository(config, repository) {
    const repositories = await listIndexedRepositories(config);
    const next = repositories.filter((item) => item.repoId !== repository.repoId);
    next.push(repository);
    await writeRepositoryRegistry(config, next);
}
export async function removeIndexedRepository(config, repoId) {
    const repositories = await listIndexedRepositories(config);
    const next = repositories.filter((item) => item.repoId !== repoId);
    await writeRepositoryRegistry(config, next);
}
export async function resolveRepository(config, reference) {
    if (!reference || !reference.trim()) {
        return undefined;
    }
    const normalized = reference.trim();
    const normalizedPath = path.resolve(normalized);
    const repositories = await listIndexedRepositories(config);
    const byId = repositories.find((repository) => repository.repoId === normalized);
    if (byId)
        return byId;
    const byRoot = repositories.find((repository) => path.resolve(repository.repoRoot) === normalizedPath);
    if (byRoot)
        return byRoot;
    const byName = repositories.filter((repository) => repository.repoName === normalized || path.basename(repository.repoRoot) === normalized);
    if (byName.length === 1) {
        return byName[0];
    }
    if (byName.length > 1) {
        throw new Error(`Repository reference is ambiguous: ${reference}`);
    }
    throw new Error(`Repository is not indexed: ${reference}`);
}
