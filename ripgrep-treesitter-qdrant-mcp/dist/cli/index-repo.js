import { indexRepository } from "../core/index-engine.js";
async function main() {
    const repoRoot = process.argv[2] || process.env.REPO_ROOT || ".";
    console.log(JSON.stringify(await indexRepository(repoRoot), null, 2));
}
main().catch((error) => {
    console.error(error);
    process.exit(1);
});
