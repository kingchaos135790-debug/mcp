import { hybridCodeSearch, lexicalCodeSearch, listIndexedCodebases, searchEngineHealth, semanticCodeSearch, } from "../core/search-engine.js";
import { indexRepository, removeIndexedRepositoryData } from "../core/index-engine.js";
function parseArgs() {
    const command = process.argv[2];
    const rawPayload = process.argv[3];
    const payload = rawPayload ? JSON.parse(rawPayload) : {};
    return { command, payload };
}
async function main() {
    const { command, payload } = parseArgs();
    if (!command) {
        throw new Error("Missing command name.");
    }
    switch (command) {
        case "semantic_code_search":
            process.stdout.write(JSON.stringify(await semanticCodeSearch(payload.query, payload.limit, payload.repo), null, 2));
            return;
        case "lexical_code_search":
            process.stdout.write(JSON.stringify(await lexicalCodeSearch(payload.query, payload.limit, payload.repo, payload.case_mode), null, 2));
            return;
        case "hybrid_code_search":
            process.stdout.write(JSON.stringify(await hybridCodeSearch(payload.query, payload.limit, payload.repo), null, 2));
            return;
        case "server_health":
            process.stdout.write(JSON.stringify(await searchEngineHealth(), null, 2));
            return;
        case "list_indexed_repositories":
            process.stdout.write(JSON.stringify(await listIndexedCodebases(), null, 2));
            return;
        case "index_repository":
            process.stdout.write(JSON.stringify(await indexRepository(payload.repoRoot), null, 2));
            return;
        case "remove_indexed_repository":
            process.stdout.write(JSON.stringify(await removeIndexedRepositoryData(payload.repoRoot || payload.repo), null, 2));
            return;
        default:
            throw new Error(`Unsupported command: ${command}`);
    }
}
main().catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exit(1);
});

