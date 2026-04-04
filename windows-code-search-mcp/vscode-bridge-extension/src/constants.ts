export const MAX_FOLDER_FILES = 200;
export const MAX_FILE_BYTES = 256 * 1024;
export const MAX_FOLDER_SUMMARY_ENTRIES = 400;

export const SKIPPED_DIRECTORY_NAMES = new Set([
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
