import assert from "node:assert/strict";
import test from "node:test";

import { extractCodeChunks } from "../dist/lib/tree-sitter-utils.js";

const cases = [
  {
    language: "go",
    file: "sample.go",
    source: "package p\nfunc Add(a int, b int) int { return a + b }\ntype User struct { Name string }",
    expected: [["Add", "function"], ["User", "type"]],
  },
  {
    language: "rust",
    file: "sample.rs",
    source: "struct User { name: String }\nimpl User { fn name(&self) -> &str { &self.name } }",
    expected: [["User", "struct"], ["name", "function"]],
  },
  {
    language: "java",
    file: "Sample.java",
    source: "class Sample { Sample() {} int add(int a, int b) { return a + b; } }",
    expected: [["Sample", "class"], ["Sample", "constructor"], ["add", "method"]],
  },
  {
    language: "c",
    file: "sample.c",
    source: "struct User { int id; };\nint add(int a, int b) { return a + b; }",
    expected: [["User", "struct"], ["add", "function"]],
  },
  {
    language: "cpp",
    file: "sample.cpp",
    source: "class Sample { public: int add(int a, int b) { return a + b; } };",
    expected: [["Sample", "class"], ["add", "function"]],
  },
  {
    language: "csharp",
    file: "Sample.cs",
    source: "class Sample { public Sample() {} int Add(int a, int b) => a + b; }",
    expected: [["Sample", "class"], ["Sample", "constructor"], ["Add", "method"]],
  },
  {
    language: "ruby",
    file: "sample.rb",
    source: "class Sample\n  def add(a, b)\n    a + b\n  end\nend",
    expected: [["Sample", "class"], ["add", "method"]],
  },
  {
    language: "php",
    file: "sample.php",
    source: "<?php class Sample { public function add($a, $b) { return $a + $b; } }",
    expected: [["Sample", "class"], ["add", "method"]],
  },
];

for (const sample of cases) {
  test(`extracts syntax-aware ${sample.language} chunks`, () => {
    const chunks = extractCodeChunks(sample.file, sample.source);
    assert.notEqual(chunks[0]?.kind, "file");
    assert.equal(chunks[0]?.language, sample.language);

    const actual = chunks.map((chunk) => [chunk.symbol, chunk.kind]);
    for (const expected of sample.expected) {
      assert.ok(
        actual.some(([symbol, kind]) => symbol === expected[0] && kind === expected[1]),
        `Expected ${expected[1]} ${expected[0]} in ${JSON.stringify(actual)}`,
      );
    }
  });
}

test("unknown extensions still use a file-level fallback", () => {
  const chunks = extractCodeChunks("notes.custom", "some content");
  assert.deepEqual(chunks.map(({ symbol, kind, language }) => ({ symbol, kind, language })), [
    { symbol: "file", kind: "file", language: "unknown" },
  ]);
});
