import Parser from "tree-sitter";
import JavaScript from "tree-sitter-javascript";
import TypeScript from "tree-sitter-typescript";
import Python from "tree-sitter-python";
function detectLanguage(filePath) {
    if (filePath.endsWith('.ts'))
        return 'typescript';
    if (filePath.endsWith('.tsx'))
        return 'tsx';
    if (filePath.endsWith('.js') || filePath.endsWith('.jsx') || filePath.endsWith('.mjs') || filePath.endsWith('.cjs'))
        return 'javascript';
    if (filePath.endsWith('.py'))
        return 'python';
    return 'unknown';
}
function createParser(language) {
    const parser = new Parser();
    switch (language) {
        case 'javascript':
            parser.setLanguage(JavaScript);
            return parser;
        case 'typescript':
            parser.setLanguage(TypeScript.typescript);
            return parser;
        case 'tsx':
            parser.setLanguage(TypeScript.tsx);
            return parser;
        case 'python':
            parser.setLanguage(Python);
            return parser;
        default:
            return null;
    }
}
function nodeText(source, startIndex, endIndex) {
    return source.slice(startIndex, endIndex);
}
function pushChunk(chunks, source, node, symbol, kind, language) {
    chunks.push({
        symbol,
        kind,
        language,
        startLine: node.startPosition.row + 1,
        endLine: node.endPosition.row + 1,
        text: nodeText(source, node.startIndex, node.endIndex),
    });
}
function walk(source, node, chunks, language) {
    const type = node.type;
    if (language === 'python' && type === 'function_definition') {
        const nameNode = node.childForFieldName('name');
        pushChunk(chunks, source, node, nameNode?.text ?? 'anonymous', 'function', language);
    }
    else if (language === 'python' && type === 'class_definition') {
        const nameNode = node.childForFieldName('name');
        pushChunk(chunks, source, node, nameNode?.text ?? 'anonymous', 'class', language);
    }
    else if ((language === 'typescript' || language === 'tsx' || language === 'javascript') && type === 'function_declaration') {
        const nameNode = node.childForFieldName('name');
        pushChunk(chunks, source, node, nameNode?.text ?? 'anonymous', 'function', language);
    }
    else if ((language === 'typescript' || language === 'tsx' || language === 'javascript') && type === 'class_declaration') {
        const nameNode = node.childForFieldName('name');
        pushChunk(chunks, source, node, nameNode?.text ?? 'anonymous', 'class', language);
    }
    else if ((language === 'typescript' || language === 'tsx' || language === 'javascript') && type === 'method_definition') {
        const nameNode = node.childForFieldName('name');
        pushChunk(chunks, source, node, nameNode?.text ?? 'anonymous', 'method', language);
    }
    else if ((language === 'typescript' || language === 'tsx' || language === 'javascript') && type === 'lexical_declaration') {
        for (const child of node.namedChildren) {
            if (child.type === 'variable_declarator') {
                const nameNode = child.childForFieldName('name');
                const valueNode = child.childForFieldName('value');
                if (valueNode && (valueNode.type === 'arrow_function' || valueNode.type === 'function')) {
                    pushChunk(chunks, source, node, nameNode?.text ?? 'anonymous', 'function_variable', language);
                }
            }
        }
    }
    for (const child of node.namedChildren) {
        walk(source, child, chunks, language);
    }
}
export function extractCodeChunks(filePath, source) {
    const language = detectLanguage(filePath);
    const parser = createParser(language);
    const fallbackChunk = () => {
        const lines = source.split(/\r?\n/);
        return [{ symbol: 'file', kind: 'file', language, startLine: 1, endLine: lines.length, text: source }];
    };
    if (!parser) {
        return fallbackChunk();
    }
    let tree;
    try {
        tree = parser.parse(source);
    }
    catch {
        return fallbackChunk();
    }
    const chunks = [];
    walk(source, tree.rootNode, chunks, language);
    if (chunks.length === 0) {
        chunks.push(...fallbackChunk());
    }
    return chunks;
}
