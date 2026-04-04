import fg from "fast-glob";
import fs from "node:fs/promises";
import path from "node:path";
import { getWindowsReservedDeviceExcludeGlobs, isWindowsReservedDevicePath } from "./windows-path-utils.js";
const MAX_SOURCE_FILE_BYTES = Number.parseInt(process.env.MAX_SOURCE_FILE_BYTES || "1048576", 10);
export async function listSourceFiles(root) {
    const patterns = [
        "**/*.{ts,tsx,js,jsx,mjs,cjs,py,go,rs,java,c,cpp,h,hpp,cs,rb,php}",
        "!**/node_modules/**",
        "!**/.git/**",
        "!**/dist/**",
        "!**/build/**",
        "!**/.next/**",
        "!**/coverage/**",
        "!**/vendor/**",
        "!**/vendors/**",
        "!**/third_party/**",
        "!**/third-party/**",
        "!**/generated/**",
        "!**/*.min.js",
        ...getWindowsReservedDeviceExcludeGlobs(),
    ];
    const matches = await fg(patterns, {
        cwd: root,
        absolute: true,
        dot: false,
        onlyFiles: true,
    });
    const filteredMatches = [];
    for (const file of matches) {
        if (isWindowsReservedDevicePath(file)) {
            continue;
        }
        try {
            const stat = await fs.stat(file);
            if (Number.isFinite(MAX_SOURCE_FILE_BYTES) && MAX_SOURCE_FILE_BYTES > 0 && stat.size > MAX_SOURCE_FILE_BYTES) {
                continue;
            }
            filteredMatches.push(file);
        }
        catch {
            // Skip files that disappear or cannot be read during discovery.
        }
    }
    return filteredMatches.sort();
}
export async function readText(filePath) {
    return fs.readFile(filePath, "utf8");
}
export function toPosixRelative(root, filePath) {
    return path.relative(root, filePath).split(path.sep).join("/");
}
