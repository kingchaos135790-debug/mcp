import path from "node:path";
const WINDOWS_RESERVED_DEVICE_NAMES = new Set([
    "con",
    "prn",
    "aux",
    "nul",
    "com1",
    "com2",
    "com3",
    "com4",
    "com5",
    "com6",
    "com7",
    "com8",
    "com9",
    "lpt1",
    "lpt2",
    "lpt3",
    "lpt4",
    "lpt5",
    "lpt6",
    "lpt7",
    "lpt8",
    "lpt9",
]);
function reservedStem(name) {
    const trimmed = name.trim().replace(/[. ]+$/g, "");
    if (!trimmed) {
        return "";
    }
    return trimmed.split(".")[0]?.toLowerCase() || "";
}
export function isWindowsReservedDevicePath(filePath) {
    if (!filePath) {
        return false;
    }
    const normalizedPath = filePath.replace(/[\\/]+$/, "");
    const baseName = path.basename(normalizedPath);
    return WINDOWS_RESERVED_DEVICE_NAMES.has(reservedStem(baseName));
}
export function getWindowsReservedDeviceExcludeGlobs() {
    return Array.from(WINDOWS_RESERVED_DEVICE_NAMES).flatMap((name) => [
        `!${name}`,
        `!${name}.*`,
        `!**/${name}`,
        `!**/${name}.*`,
    ]);
}
