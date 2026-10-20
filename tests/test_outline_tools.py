"""Tests for the outline_file structural navigation tool."""

from __future__ import annotations

from pathlib import Path

from clanker.tools.outline_tools import outline_file


class TestOutlineFilePython:
    def test_outline_python_classes_and_functions(self, tmp_path: Path) -> None:
        py_file = tmp_path / "sample.py"
        py_file.write_text(
            '"""Module docstring."""\n\n'
            "class Animal:\n"
            '    """Base animal class."""\n'
            "    def __init__(self, name: str, age: int = 0) -> None:\n"
            "        self.name = name\n"
            "        self.age = age\n\n"
            "    def speak(self) -> str:\n"
            '        return "..."\n\n'
            "class Dog(Animal):\n"
            "    def speak(self) -> str:\n"
            '        return "woof"\n\n'
            "async def fetch_data(url: str, timeout: int = 10) -> dict:\n"
            '    return {"ok": True}\n'
        )

        res = outline_file.invoke({"file_path": str(py_file)})
        assert res["ok"] is True
        assert res["language"] == "python"
        assert res["total_symbols"] == 3  # Animal, Dog, fetch_data (top-level)

        outline = res["outline"]
        assert "class Animal" in outline
        assert "def __init__(self, name: str, age: int = 0) -> None" in outline
        assert "def speak(self) -> str" in outline
        assert "class Dog(Animal)" in outline
        assert "async def fetch_data(url: str, timeout: int = 10) -> dict" in outline
        assert "# Base animal class." in outline

    def test_outline_python_max_depth(self, tmp_path: Path) -> None:
        py_file = tmp_path / "nested.py"
        py_file.write_text("class Outer:\n    def inner_method(self):\n        pass\n")
        # Depth 1 should show Outer, but not inner_method
        res = outline_file.invoke({"file_path": str(py_file), "max_depth": 1})
        assert res["ok"] is True
        assert "class Outer" in res["outline"]
        assert "inner_method" not in res["outline"]

    def test_outline_python_syntax_error_fallback(self, tmp_path: Path) -> None:
        py_file = tmp_path / "broken.py"
        py_file.write_text("def broken_syntax(:\n    pass\nclass Recovered:\n    pass\n")
        res = outline_file.invoke({"file_path": str(py_file)})
        assert res["ok"] is True
        # Generic fallback catches def / class tokens
        assert "broken_syntax" in res["outline"] or "Recovered" in res["outline"]


class TestOutlineFileOtherLanguages:
    def test_outline_typescript(self, tmp_path: Path) -> None:
        ts_file = tmp_path / "service.ts"
        ts_file.write_text(
            "export interface UserProfile {\n"
            "  id: string;\n"
            "  name: string;\n"
            "}\n\n"
            "export type Status = 'active' | 'inactive';\n\n"
            "export class UserService extends BaseService {\n"
            "  async getUser(id: string): Promise<UserProfile> {\n"
            "    return fetchUser(id);\n"
            "  }\n"
            "}\n\n"
            "export const calculateScore = (profile: UserProfile): number => {\n"
            "  return 42;\n"
            "};\n"
        )
        res = outline_file.invoke({"file_path": str(ts_file)})
        assert res["ok"] is True
        assert res["language"] == "javascript/typescript"
        assert "interface UserProfile" in res["outline"]
        assert "type Status" in res["outline"]
        assert "class UserService" in res["outline"]
        assert "calculateScore" in res["outline"]

    def test_outline_go(self, tmp_path: Path) -> None:
        go_file = tmp_path / "main.go"
        go_file.write_text(
            "package main\n\n"
            "type Server struct {\n"
            "    port int\n"
            "}\n\n"
            "func (s *Server) Start() error {\n"
            "    return nil\n"
            "}\n\n"
            "func NewServer(port int) *Server {\n"
            "    return &Server{port: port}\n"
            "}\n"
        )
        res = outline_file.invoke({"file_path": str(go_file)})
        assert res["ok"] is True
        assert res["language"] == "go"
        assert "type Server struct" in res["outline"]
        assert "func (s *Server) Start()" in res["outline"]
        assert "func NewServer(port int) *Server" in res["outline"]

    def test_outline_rust(self, tmp_path: Path) -> None:
        rs_file = tmp_path / "lib.rs"
        rs_file.write_text(
            "pub struct Config {\n"
            "    pub timeout: u64,\n"
            "}\n\n"
            "pub enum Mode {\n"
            "    Fast,\n"
            "    Safe,\n"
            "}\n\n"
            "pub trait Runner {\n"
            "    fn run(&self);\n"
            "}\n\n"
            "pub async fn initialize() -> Result<(), String> {\n"
            "    Ok(())\n"
            "}\n"
        )
        res = outline_file.invoke({"file_path": str(rs_file)})
        assert res["ok"] is True
        assert res["language"] == "rust"
        assert "struct Config" in res["outline"]
        assert "enum Mode" in res["outline"]
        assert "trait Runner" in res["outline"]
        assert "fn initialize" in res["outline"]

    def test_outline_markdown(self, tmp_path: Path) -> None:
        md_file = tmp_path / "DOCS.md"
        md_file.write_text(
            "# Architecture\n\n"
            "Overview here.\n\n"
            "## Components\n\n"
            "### Agent Loop\n\n"
            "## Configuration\n"
        )
        res = outline_file.invoke({"file_path": str(md_file)})
        assert res["ok"] is True
        assert res["language"] == "markdown"
        assert "# Architecture" in res["outline"]
        assert "## Components" in res["outline"]
        assert "### Agent Loop" in res["outline"]
        assert "## Configuration" in res["outline"]


class TestOutlineFileEdgeCases:
    def test_nonexistent_file(self) -> None:
        res = outline_file.invoke({"file_path": "non_existent_file_xyz.py"})
        assert res["ok"] is False
        assert "not found" in res["error"].lower()

    def test_directory_error(self, tmp_path: Path) -> None:
        res = outline_file.invoke({"file_path": str(tmp_path)})
        assert res["ok"] is False
        assert "not a regular file" in res["error"].lower()

    def test_empty_file(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.py"
        empty.write_text("")
        res = outline_file.invoke({"file_path": str(empty)})
        assert res["ok"] is True
        assert res["total_symbols"] == 0
        assert "(no symbols found)" in res["outline"]

    def test_binary_file_rejected(self, tmp_path: Path) -> None:
        binary_file = tmp_path / "blob.bin"
        binary_file.write_bytes(b"\x00\x01\x02\x03\xff")
        res = outline_file.invoke({"file_path": str(binary_file)})
        assert res["ok"] is False
        assert "binary" in res["error"].lower()
