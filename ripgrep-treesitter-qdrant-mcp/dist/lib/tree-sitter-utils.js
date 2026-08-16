import Parser from "tree-sitter";
import JavaScript from "tree-sitter-javascript";
import TypeScript from "tree-sitter-typescript";
import Python from "tree-sitter-python";
import Go from "tree-sitter-go";
import Rust from "tree-sitter-rust";
import Java from "tree-sitter-java";
import C from "tree-sitter-c";
import Cpp from "tree-sitter-cpp";
import CSharp from "tree-sitter-c-sharp";
import Ruby from "tree-sitter-ruby";
import PHP from "tree-sitter-php";
export const CODE_CHUNK_SCHEMA_VERSION = 2;
const JS_LANGUAGES = new Set(["javascript", "typescript", "tsx"]);
const CHUNK_RULES = {
    python: {
        function_definition: { kind: "function" },
        class_definition: { kind: "class" },
    },
    go: {
        function_declaration: { kind: "function" },
        method_declaration: { kind: "method" },
        type_spec: { kind: "type" },
        type_alias: { kind: "type" },
    },
    rust: {
        function_item: { kind: "function" },
        struct_item: { kind: "struct" },
        enum_item: { kind: "enum" },
        trait_item: { kind: "trait" },
        type_item: { kind: "type" },
    },
    java: {
        method_declaration: { kind: "method" },
        constructor_declaration: { kind: "constructor" },
        compact_constructor_declaration: { kind: "constructor" },
        class_declaration: { kind: "class" },
        interface_declaration: { kind: "interface" },
        enum_declaration: { kind: "enum" },
        annotation_type_declaration: { kind: "annotation" },
    },
    c: {
        function_definition: { kind: "function", declaratorSymbol: true },
        struct_specifier: { kind: "struct" },
        enum_specifier: { kind: "enum" },
    },
    cpp: {
        function_definition: { kind: "function", declaratorSymbol: true },
        class_specifier: { kind: "class" },
        struct_specifier: { kind: "struct" },
        enum_specifier: { kind: "enum" },
    },
    csharp: {
        method_declaration: { kind: "method" },
        constructor_declaration: { kind: "constructor" },
        destructor_declaration: { kind: "destructor" },
        local_function_statement: { kind: "function" },
        class_declaration: { kind: "class" },
        struct_declaration: { kind: "struct" },
        interface_declaration: { kind: "interface" },
        enum_declaration: { kind: "enum" },
    },
    ruby: {
        method: { kind: "method" },
        singleton_method: { kind: "method" },
        class: { kind: "class" },
        module: { kind: "module" },
    },
    php: {
        function_definition: { kind: "function" },
        method_declaration: { kind: "method" },
        class_declaration: { kind: "class" },
        interface_declaration: { kind: "interface" },
        trait_declaration: { kind: "trait" },
        enum_declaration: { kind: "enum" },
    },
};
function detectLanguage(filePath) {
    const lowerPath = filePath.toLowerCase();
    if (lowerPath.endsWith(".ts"))
        return "typescript";
    if (lowerPath.endsWith(".tsx"))
        return "tsx";
    if (lowerPath.endsWith(".js") || lowerPath.endsWith(".jsx") || lowerPath.endsWith(".mjs") || lowerPath.endsWith(".cjs"))
        return "javascript";
    if (lowerPath.endsWith(".py"))
        return "python";
    if (lowerPath.endsWith(".go"))
        return "go";
    if (lowerPath.endsWith(".rs"))
        return "rust";
    if (lowerPath.endsWith(".java"))
        return "java";
    if (lowerPath.endsWith(".cpp") || lowerPath.endsWith(".hpp"))
        return "cpp";
    if (lowerPath.endsWith(".c") || lowerPath.endsWith(".h"))
        return "c";
    if (lowerPath.endsWith(".cs"))
        return "csharp";
    if (lowerPath.endsWith(".rb"))
        return "ruby";
    if (lowerPath.endsWith(".php"))
        return "php";
    return "unknown";
}
function createParser(language) {
    const parser = new Parser();
    switch (language) {
        case "javascript":
            parser.setLanguage(JavaScript);
            return parser;
        case "typescript":
            parser.setLanguage(TypeScript.typescript);
            return parser;
        case "tsx":
            parser.setLanguage(TypeScript.tsx);
            return parser;
        case "python":
            parser.setLanguage(Python);
            return parser;
        case "go":
            parser.setLanguage(Go);
            return parser;
        case "rust":
            parser.setLanguage(Rust);
            return parser;
        case "java":
            parser.setLanguage(Java);
            return parser;
        case "c":
            parser.setLanguage(C);
            return parser;
        case "cpp":
            parser.setLanguage(Cpp);
            return parser;
        case "csharp":
            parser.setLanguage(CSharp);
            return parser;
        case "ruby":
            parser.setLanguage(Ruby);
            return parser;
        case "php":
            parser.setLanguage(PHP.php);
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
function declaratorSymbol(node) {
    if (!node)
        return null;
    const nameNode = node.childForFieldName("name");
    if (nameNode) {
        return nameNode.text;
    }
    const nestedDeclarator = node.childForFieldName("declarator");
    if (nestedDeclarator) {
        return declaratorSymbol(nestedDeclarator) ?? nestedDeclarator.text;
    }
    if ([
        "identifier",
        "field_identifier",
        "type_identifier",
        "qualified_identifier",
        "namespace_identifier",
        "operator_name",
        "destructor_name",
    ].includes(node.type)) {
        return node.text;
    }
    return null;
}
function symbolForRule(node, rule) {
    if (rule.declaratorSymbol) {
        const declarator = node.childForFieldName("declarator");
        return declaratorSymbol(declarator) ?? "anonymous";
    }
    const field = rule.symbolField ?? "name";
    return node.childForFieldName(field)?.text ?? "anonymous";
}
function walk(source, node, chunks, language) {
    const type = node.type;
    if (JS_LANGUAGES.has(language)) {
        if (type === "function_declaration") {
            pushChunk(chunks, source, node, node.childForFieldName("name")?.text ?? "anonymous", "function", language);
        }
        else if (type === "class_declaration") {
            pushChunk(chunks, source, node, node.childForFieldName("name")?.text ?? "anonymous", "class", language);
        }
        else if (type === "method_definition") {
            pushChunk(chunks, source, node, node.childForFieldName("name")?.text ?? "anonymous", "method", language);
        }
        else if (type === "lexical_declaration" || type === "variable_declaration") {
            for (const child of node.namedChildren) {
                if (child.type !== "variable_declarator")
                    continue;
                const nameNode = child.childForFieldName("name");
                const valueNode = child.childForFieldName("value");
                if (valueNode && (valueNode.type === "arrow_function" || valueNode.type === "function")) {
                    pushChunk(chunks, source, node, nameNode?.text ?? "anonymous", "function_variable", language);
                }
            }
        }
    }
    else {
        const rule = CHUNK_RULES[language]?.[type];
        if (rule) {
            pushChunk(chunks, source, node, symbolForRule(node, rule), rule.kind, language);
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
        return [{ symbol: "file", kind: "file", language, startLine: 1, endLine: lines.length, text: source }];
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
