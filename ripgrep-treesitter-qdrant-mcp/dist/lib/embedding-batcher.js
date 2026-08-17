const DEFAULT_WINDOW_MULTIPLIER = 4;
export class EmbeddingBatchQueue {
    batchSize;
    embed;
    onEmbedded;
    pending = [];
    windowSize;
    constructor(batchSize, embed, onEmbedded, windowMultiplier = DEFAULT_WINDOW_MULTIPLIER) {
        this.batchSize = batchSize;
        this.embed = embed;
        this.onEmbedded = onEmbedded;
        if (!Number.isInteger(batchSize) || batchSize <= 0) {
            throw new Error("Embedding batch size must be a positive integer.");
        }
        if (!Number.isInteger(windowMultiplier) || windowMultiplier <= 0) {
            throw new Error("Embedding batch window multiplier must be a positive integer.");
        }
        this.windowSize = batchSize * windowMultiplier;
    }
    async add(input, value) {
        this.pending.push({ input, value });
        if (this.pending.length >= this.windowSize) {
            await this.flushWindow(this.windowSize);
        }
    }
    async flush() {
        while (this.pending.length > 0) {
            await this.flushWindow(Math.min(this.windowSize, this.pending.length));
        }
    }
    get pendingCount() {
        return this.pending.length;
    }
    async flushWindow(count) {
        const window = this.pending
            .splice(0, count)
            .sort((a, b) => a.input.length - b.input.length);
        for (let offset = 0; offset < window.length; offset += this.batchSize) {
            const batch = window.slice(offset, offset + this.batchSize);
            const vectors = await this.embed(batch.map((item) => item.input));
            if (vectors.length !== batch.length) {
                throw new Error(`Embedding batch returned ${vectors.length} vectors; expected ${batch.length}.`);
            }
            for (let index = 0; index < batch.length; index += 1) {
                await this.onEmbedded(batch[index].value, vectors[index]);
            }
        }
    }
}
