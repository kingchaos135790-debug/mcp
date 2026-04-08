from pathlib import Path

root = Path(r"E:\Program Files\mcp\windows-code-search-mcp")

ext_path = root / "server_extensions.py"
text = ext_path.read_text(encoding="utf-8")
old = '''        if "expected text mismatch before applying edit" in normalized_error:
            guidance = (
                "Re-read the exact range with get_vscode_file_range, retry with fresh expected_text, and consider a narrower edit or smaller anchored change."
            )
        elif "resource not found" in normalized_error:
'''
new = '''        if (
            "expected text mismatch before applying edit" in normalized_error
            or "could not reliably locate edit target after drift" in normalized_error
            or ("edit target" in normalized_error and "drift" in normalized_error)
        ):
            guidance = (
                "Re-read the exact range with get_vscode_file_range, retry with fresh expected_text, and consider a narrower edit or smaller anchored change."
            )
        elif "resource not found" in normalized_error:
'''
if old not in text:
    raise SystemExit("expected server_extensions.py block not found")
ext_path.write_text(text.replace(old, new, 1), encoding="utf-8")

test_path = root / "tests" / "test_server_extensions.py"
test_text = test_path.read_text(encoding="utf-8")
anchor = '''    def test_require_vscode_command_success_raises_with_resource_path_hint(self) -> None:
'''
insert = '''    def test_require_vscode_command_success_raises_with_drift_recovery_hint(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "narrower edit"):
            require_vscode_command_success(
                "request_vscode_edit",
                {"status": "error", "error": "Could not reliably locate edit target after drift."},
            )

'''
if insert not in test_text:
    if anchor not in test_text:
        raise SystemExit("expected test anchor not found")
    test_text = test_text.replace(anchor, insert + anchor, 1)
    test_path.write_text(test_text, encoding="utf-8")
