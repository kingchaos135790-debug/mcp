"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.ContextStore = void 0;
class ContextStore {
    extensionContext;
    items = [];
    constructor(extensionContext) {
        this.extensionContext = extensionContext;
        const saved = this.extensionContext.workspaceState.get('windowsCodeSearchBridge.contextItems', []);
        this.items = Array.isArray(saved) ? saved : [];
    }
    all() {
        return [...this.items];
    }
    async replace(items) {
        this.items = items;
        await this.persist();
    }
    async add(item) {
        this.items = [item, ...this.items.filter((existing) => existing.id !== item.id)];
        await this.persist();
    }
    async remove(id) {
        this.items = this.items.filter((item) => item.id !== id);
        await this.persist();
    }
    async clear() {
        this.items = [];
        await this.persist();
    }
    async persist() {
        await this.extensionContext.workspaceState.update('windowsCodeSearchBridge.contextItems', this.items);
    }
}
exports.ContextStore = ContextStore;
//# sourceMappingURL=contextStore.js.map