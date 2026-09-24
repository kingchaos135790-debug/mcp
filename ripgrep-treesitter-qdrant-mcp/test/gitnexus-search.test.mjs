import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { normalizeGitNexusResults, parseGitNexusJson, runGitNexus, syncGitNexusExcludes } from '../dist/lib/gitnexus-utils.js';
import { fuseResults, hybridCodeSearch } from '../dist/core/search-engine.js';
import { indexRepository, removeIndexedRepositoryData } from '../dist/core/index-engine.js';

const repo = { repoId: 'repo-1', repoName: 'app', repoRoot: 'C:/app' };
const symbol = { id: 'Function:src/auth.ts:login', name: 'login', type: 'Function', filePath: 'src/auth.ts', startLine: 2, endLine: 8, process_id: 'flow-1', content: 'function login() {}' };
const response = {
  processes: [{ id: 'flow-1', summary: 'Login flow', process_type: 'cross_community' }],
  process_symbols: [symbol], definitions: [symbol],
};

test('normalizes graph symbols, preserves flow context, and deduplicates definitions', () => {
  const hits = normalizeGitNexusResults(response, repo, 10);
  assert.equal(hits.length, 1);
  assert.equal(hits[0].filePath, 'src/auth.ts');
  assert.equal(hits[0].startLine, 2);
  assert.equal(hits[0].processes[0].label, 'Login flow');
  assert.equal(hits[0].source, 'gitnexus');
  assert.deepEqual(normalizeGitNexusResults({ processes: [], process_symbols: [], definitions: [] }, repo, 10), []);
});

test('parses CLI diagnostics but refuses malformed, partial, and error responses', () => {
  assert.deepEqual(parseGitNexusJson('GitNexus startup\n' + JSON.stringify(response)), response);
  assert.throws(() => parseGitNexusJson(''), /invalid or empty/);
  assert.throws(() => normalizeGitNexusResults({ error: 'locked' }, repo, 8), /locked/);
  assert.throws(() => normalizeGitNexusResults({ ...response, partial: true }, repo, 8), /partial/);
  assert.throws(() => normalizeGitNexusResults({}, repo, 8), /Unrecognized/);
});

test('fusion matches Windows paths and line ranges without merging different repositories', () => {
  const graph = normalizeGitNexusResults(response, repo, 10);
  const lexical = [{ repoId: repo.repoId, file: '.\\src\\auth.ts', line: 3, text: 'login' }];
  const fused = fuseResults(graph, lexical, 8);
  assert.equal(fused.length, 1);
  assert.equal(fused[0].source, 'hybrid');
  assert.deepEqual(fused[0].sources, ['gitnexus', 'lexical']);
  assert.equal(fused[0].processes[0].id, 'flow-1');
  assert.equal(fuseResults(graph, [{ ...lexical[0], repoId: 'other' }], 8).length, 2);
  assert.equal(fuseResults([graph[0], graph[0]], lexical, 8)[0].fusionScore, fused[0].fusionScore);
});

test('index/search/cleanup use GitNexus without a vector service; errors retain lexical hits', async () => {
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'mcp-gitnexus-'));
  const prior = { ...process.env };
  try {
    const root = path.join(temp, 'repo with spaces');
    await fs.mkdir(root);
    await fs.writeFile(path.join(root, 'auth.ts'), 'export function login() { return true; }\n');
    const cli = path.join(temp, 'fake cli.mjs');
    const log = path.join(temp, 'calls.jsonl');
    await fs.writeFile(cli, `import fs from 'node:fs'; import path from 'node:path';
      const args = process.argv.slice(2);
      fs.appendFileSync(${JSON.stringify(log)}, JSON.stringify({args, home: process.env.GITNEXUS_HOME, storage: process.env.GITNEXUS_STORAGE_ROOT})+'\\n');
      if (args[0] === 'analyze') {
        const name = args[args.indexOf('--name')+1];
        const storagePath = path.join(process.env.GITNEXUS_STORAGE_ROOT, name);
        fs.mkdirSync(storagePath, {recursive:true});
        fs.mkdirSync(process.env.GITNEXUS_HOME, {recursive:true});
        fs.writeFileSync(path.join(process.env.GITNEXUS_HOME, 'registry.json'), JSON.stringify([{name,storagePath}]));
        fs.writeFileSync(path.join(storagePath, 'meta.json'), JSON.stringify({indexedAt:new Date().toISOString(),stats:{embeddings:0},capabilities:{fts:{status:args.includes('--repair-fts')?'available':'unavailable'}}}));
      }
      if (args[0] === 'query') {
        if (process.env.TEST_GRAPH_FAIL) { console.error('graph is locked'); process.exit(1); }
        console.log(JSON.stringify({processes:[], process_symbols:[], definitions:[{id:'login',name:'login',filePath:'auth.ts',startLine:1,endLine:1,content:'export function login() { return true; }'}]}));
      }
    `);
    process.env.INDEX_ROOT = path.join(temp, 'index');
    process.env.GITNEXUS_CLI_PATH = cli;
    process.env.GITNEXUS_NODE_EXE = process.execPath;
    process.env.QDRANT_URL = 'http://127.0.0.1:1';
    const indexed = await indexRepository(root);
    assert.equal(indexed.gitnexus.embeddings, false);
    assert.equal(indexed.changedFiles, 1);
    assert.equal((await indexRepository(root)).unchangedFiles, 1);
    await fs.writeFile(path.join(root, '.gitnexusrc'), '{"analyze":{"embeddings":true}}');
    await assert.rejects(() => indexRepository(root), /disables embeddings/);
    await fs.rm(path.join(root, '.gitnexusrc'));
    const query = '--query; $(echo unsafe) "quoted"';
    await hybridCodeSearch(query, 8, root);
    const hits = await hybridCodeSearch('login', 8, root);
    assert.equal(hits.gitnexus[0].symbol, 'login');
    assert.ok(hits.lexical.length);
    assert.ok(hits.fused.some(hit => hit.source === 'hybrid'));
    assert.equal('semantic' in hits, false);
    process.env.TEST_GRAPH_FAIL = '1';
    const fallback = await hybridCodeSearch('login', 8, root);
    assert.deepEqual(fallback.gitnexus, []);
    assert.ok(fallback.fused.length);
    assert.ok(fallback.status.warnings.some(warning => warning.includes('graph is locked')));
    assert.equal(fallback.status.gitnexus[0].available, false);
    await assert.rejects(() => hybridCodeSearch('login', 8, 'unknown-repo'), /not indexed/);
    const removed = await removeIndexedRepositoryData(root);
    assert.equal(removed.removedGraph, true);
    const calls = (await fs.readFile(log, 'utf8')).trim().split('\n').map(JSON.parse);
    assert.ok(calls.some(call => call.args.at(-1) === query));
    assert.ok(calls[0].args.includes('--index-only'));
    assert.ok(calls[0].args.includes('--drop-embeddings'));
    assert.ok(calls.some(call => call.args.includes('--repair-fts')));
    assert.ok(calls.every(call => call.home.startsWith(temp) && call.storage.startsWith(temp)));
    assert.ok(calls.some(call => call.args[0] === 'remove'));
  } finally {
    for (const key of Object.keys(process.env)) if (!(key in prior)) delete process.env[key];
    Object.assign(process.env, prior);
    await fs.rm(temp, { recursive: true, force: true });
  }
});

test('CLI timeout is reported instead of hanging', async () => {
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'mcp-gitnexus-timeout-'));
  const priorCli = process.env.GITNEXUS_CLI_PATH;
  const priorNode = process.env.GITNEXUS_NODE_EXE;
  try {
    const cli = path.join(temp, 'slow.mjs');
    await fs.writeFile(cli, 'setInterval(() => {}, 1000);');
    process.env.GITNEXUS_CLI_PATH = cli;
    process.env.GITNEXUS_NODE_EXE = process.execPath;
    await assert.rejects(() => runGitNexus(['query'], 100), /timeout/);
  } finally {
    if (priorCli === undefined) delete process.env.GITNEXUS_CLI_PATH; else process.env.GITNEXUS_CLI_PATH = priorCli;
    if (priorNode === undefined) delete process.env.GITNEXUS_NODE_EXE; else process.env.GITNEXUS_NODE_EXE = priorNode;
    await fs.rm(temp, { recursive: true, force: true });
  }
});

test('managed graph exclusions preserve user rules and avoid repeated file writes', async () => {
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'mcp-gitnexus-ignore-'));
  try {
    const file = path.join(temp, '.gitnexusignore');
    assert.equal(await syncGitNexusExcludes(temp, []), false);
    await fs.writeFile(file, '# user rule\nprivate/\n');
    assert.equal(await syncGitNexusExcludes(temp, ['Library/**', 'Logs/**']), true);
    const content = await fs.readFile(file, 'utf8');
    assert.ok(content.startsWith('# user rule\nprivate/\n'));
    assert.ok(content.includes('Library/**'));
    assert.equal(await syncGitNexusExcludes(temp, ['Library/**', 'Logs/**']), false);
    await syncGitNexusExcludes(temp, []);
    assert.ok((await fs.readFile(file, 'utf8')).startsWith('# user rule\nprivate/\n'));
    assert.ok(!(await fs.readFile(file, 'utf8')).includes('Library/**'));
  } finally { await fs.rm(temp, { recursive: true, force: true }); }
});
