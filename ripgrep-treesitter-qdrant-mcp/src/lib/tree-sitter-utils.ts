import Parser from "tree-sitter";
import JavaScript from "tree-sitter-javascript";
import TypeScript from "tree-sitter-typescript";
import Python from "tree-sitter-python";

export type SupportedLanguage = "javascript" | "typescript" | "tsx" | "python" | "unknown";

export type CodeChunk = {
  symbol: string;
  kind: string;
  language: SupportedLanguage;
  startLine: number;
  endLine: number;
  text: string;
};

function detectLanguage(filePath: string): SupportedLanguage {
  if (filePath.endsWith('.ts')) return 'typescript';
  if (filePath.endsWith('.tsx')) return 'tsx';
  if (filePath.endsWith('.js') || filePath.endsWith('.jsx') || filePath.endsWith('.mjs') || filePath.endsWith('.cjs')) return 'javascript';
  if (filePath.endsWith('.py')) return 'python';
  return 'unknown';
}

function createParser(language: SupportedLanguage): Parser | null {
  const parser = new Parser();
  switch (language) {
    case 'javascript':
      parser.setLanguage(JavaScript as any);
      return parser;
    case 'typescript':
      parser.setLanguage((TypeScript as any).typescript);
      return parser;
    case 'tsx':
      parser.setLanguage((TypeScript as any).tsx);
      return parser;
    case 'python':
      parser.setLanguage(Python as any);
      return parser;
    default:
      return null;
  }
}

function nodeText(source: string, startIndex: number, endIndex: number): string {
  return source.slice(startIndex, endIndex);
}

function pushChunk(chunks: CodeChunk[], source: string, node: Parser.SyntaxNode, symbol: string, kind: string, language: SupportedLanguage) {
  chunks.push({
    symbol,
    kind,
    language,
    startLine: node.startPosition.row + 1,
    endLine: node.endPosition.row + 1,
    text: nodeText(source, node.startIndex, node.endIndex),
  });
}

function walk(source: string, node: Parser.SyntaxNode, chunks: CodeChunk[], language: SupportedLanguage): void {
  const type = node.type;
  if (language === 'python' && type === 'function_definition') {
    const nameNode = node.childForFieldName('name');
    pushChunk(chunks, source, node, nameNode?.text ?? 'anonymous', 'function', language);
  } else if (language === 'python' && type === 'class_definition') {
    const nameNode = node.childForFieldName('name');
    pushChunk(chunks, source, node, nameNode?.text ?? 'anonymous', 'class', language);
  } else if ((language === 'typescript' || language === 'tsx' || language === 'javascript') && type === 'function_declaration') {
    const nameNode = node.childForFieldName('name');
    pushChunk(chunks, source, node, nameNode?.text ?? 'anonymous', 'function', language);
  } else if ((language === 'typescript' || language === 'tsx' || language === 'javascript') && type === 'class_declaration') {
    const nameNode = node.childForFieldName('name');
    pushChunk(chunks, source, node, nameNode?.text ?? 'anonymous', 'class', language);
  } else if ((language === 'typescript' || language === 'tsx' || language === 'javascript') && type === 'method_definition') {
    const nameNode = node.childForFieldName('name');
    pushChunk(chunks, source, node, nameNode?.text ?? 'anonymous', 'method', language);
  } else if ((language === 'typescript' || language === 'tsx' || language === 'javascript') && type === 'lexical_declaration') {
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

export function extractCodeChunks(filePath: string, source: string): CodeChunk[] {
  const language = detectLanguage(filePath);
  const parser = createParser(language);
  const fallbackChunk = () => {
    const lines = source.split(/\r?\n/);
    return [{ symbol: 'file', kind: 'file', language, startLine: 1, endLine: lines.length, text: source }];
  };
  if (!parser) {
    return fallbackChunk();
  }
  let tree: Parser.Tree;
  try {
    tree = parser.parse(source);
  } catch {
    return fallbackChunk();
  }
  const chunks: CodeChunk[] = [];
  walk(source, tree.rootNode, chunks, language);
  if (chunks.length === 0) {
    chunks.push(...fallbackChunk());
  }
  return chunks;
}
