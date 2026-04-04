"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.SKIPPED_DIRECTORY_NAMES = exports.MAX_FOLDER_SUMMARY_ENTRIES = exports.MAX_FILE_BYTES = exports.MAX_FOLDER_FILES = void 0;
exports.MAX_FOLDER_FILES = 200;
exports.MAX_FILE_BYTES = 256 * 1024;
exports.MAX_FOLDER_SUMMARY_ENTRIES = 400;
exports.SKIPPED_DIRECTORY_NAMES = new Set([
    '.git',
    '.hg',
    '.next',
    '.nuxt',
    '.svn',
    '.turbo',
    '.venv',
    'bin',
    'build',
    'coverage',
    'dist',
    'node_modules',
    'obj',
    'out',
    'target'
]);
//# sourceMappingURL=constants.js.map