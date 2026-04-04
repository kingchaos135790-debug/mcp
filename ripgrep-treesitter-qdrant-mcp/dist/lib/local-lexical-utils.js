import fs from "node:fs/promises";
import path from "node:path";
import { listSourceFiles, readText, toPosixRelative } from "./fs-utils.js";
function tokenize(value) {
    return Array.from(new Set(value
        .toLowerCase()
        .split(/[^a-z0-9_]+/i)
        .map((token) => token.trim())
        .filter(Boolean)));
}
function countOccurrences(haystack, needle) {
    if (!needle)
        return 0;
    let count = 0;
    let offset = 0;
    while (true) {
        const found = haystack.indexOf(needle, offset);
        if (found === -1)
            break;
        count += 1;
        offset = found + needle.length;
    }
    return count;
}
function findBestLine(content, queryTokens) {
    const lines = content.split(/\r?\n/);
    let bestLineIndex = 0;
    let bestLineScore = -1;
    for (let i = 0; i < lines.length; i += 1) {
        const candidate = lines[i].toLowerCase();
        let score = 0;
        for (const token of queryTokens) {
            score += countOccurrences(candidate, token);
        }
        if (score > bestLineScore) {
            bestLineScore = score;
            bestLineIndex = i;
        }
    }
    return {
        line: bestLineIndex + 1,
        snippet: (lines[bestLineIndex] || "").trim(),
    };
}
function buildLocalLexicalHit(doc, queryTokens, normalizedQuery, metadata = {}) {
    const haystack = `${doc.path}\n${doc.symbol}\n${doc.content}`.toLowerCase();
    let score = 0;
    if (haystack.includes(normalizedQuery)) {
        score += 20;
    }
    for (const token of queryTokens) {
        score += countOccurrences(haystack, token);
    }
    if (score <= 0) {
        return null;
    }
    const bestLine = findBestLine(doc.content, queryTokens);
    return {
        repoId: doc.repoId ?? metadata.repoId,
        repoName: doc.repoName ?? metadata.repoName,
        file: doc.path,
        line: Math.max(doc.startLine, bestLine.line),
        symbol: doc.symbol,
        kind: doc.kind,
        language: doc.language,
        score,
        snippet: bestLine.snippet,
        backend: "local",
    };
}
export async function writeLocalLexicalIndex(indexPath, repoRoot, documents, metadata = {}) {
    await fs.mkdir(path.dirname(indexPath), { recursive: true });
    const payload = {
        version: 1,
        repoId: metadata.repoId,
        repoName: metadata.repoName,
        repoRoot,
        createdAt: new Date().toISOString(),
        documentCount: documents.length,
        documents,
    };
    await fs.writeFile(indexPath, JSON.stringify(payload, null, 2), "utf8");
}
export async function readLocalLexicalIndex(indexPath) {
    try {
        const raw = await fs.readFile(indexPath, "utf8");
        const parsed = JSON.parse(raw);
        if (!parsed || !Array.isArray(parsed.documents)) {
            return null;
        }
        return parsed;
    }
    catch {
        return null;
    }
}
export function buildLocalLexicalDocument(repoRoot, filePath, content, metadata = {}) {
    const rel = toPosixRelative(repoRoot, filePath);
    const ext = path.extname(filePath).replace(/^\./, "") || "unknown";
    return {
        repoId: metadata.repoId,
        repoName: metadata.repoName,
        path: rel,
        language: ext,
        symbol: "file",
        kind: "file",
        startLine: 1,
        endLine: content.split(/\r?\n/).length,
        content,
    };
}
export async function buildLocalLexicalIndexFromRepo(repoRoot, metadata = {}) {
    const files = await listSourceFiles(repoRoot);
    const documents = [];
    for (const file of files) {
        const content = await readText(file);
        documents.push(buildLocalLexicalDocument(repoRoot, file, content, metadata));
    }
    return documents;
}
export function searchLocalLexicalDocuments(documents, query, limit = 8, metadata = {}) {
    const normalizedQuery = query.trim().toLowerCase();
    const queryTokens = tokenize(query);
    if (!normalizedQuery || queryTokens.length === 0) {
        return [];
    }
    const hits = documents
        .map((doc) => buildLocalLexicalHit(doc, queryTokens, normalizedQuery, metadata))
        .filter((hit) => Boolean(hit));
    hits.sort((a, b) => b.score - a.score || (a.repoName || "").localeCompare(b.repoName || "") || a.file.localeCompare(b.file));
    return hits.slice(0, Math.max(1, Math.min(limit, 50)));
}
export async function searchLocalLexicalIndex(indexPath, query, limit = 8) {
    const index = await readLocalLexicalIndex(indexPath);
    if (!index) {
        return [];
    }
    return searchLocalLexicalDocuments(index.documents, query, limit, {
        repoId: index.repoId,
        repoName: index.repoName,
    });
}
