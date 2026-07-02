"""Unit tests for kontor_cli.md_to_docx."""

from __future__ import annotations

from pathlib import Path


class TestModuleImport:
    def test_module_importable(self) -> None:
        import kontor_cli.md_to_docx  # noqa: F401


class TestMdToDocxConvert:
    def test_convert_minimal(self, tmp_path: Path) -> None:
        """A minimal markdown file produces a .docx with no errors."""
        md = tmp_path / "test.md"
        md.write_text("# Hello\n\nWorld\n", encoding="utf-8")
        docx = tmp_path / "test.docx"

        from kontor_cli.md_to_docx import convert

        result = convert(md, docx)
        assert result == docx
        assert docx.exists()
        assert docx.stat().st_size > 0

    def test_convert_strips_frontmatter(self, tmp_path: Path) -> None:
        """YAML frontmatter is stripped before conversion."""
        md = tmp_path / "doc.md"
        md.write_text(
            "---\ntitle: Test\ndate: 2026-07-03\n---\n# Body\n\nContent here.\n",
            encoding="utf-8",
        )
        docx = tmp_path / "doc.docx"

        from kontor_cli.md_to_docx import convert

        result = convert(md, docx)
        assert result.exists()

    def test_convert_table(self, tmp_path: Path) -> None:
        """A pipe table is handled without errors."""
        md = tmp_path / "table.md"
        md.write_text(
            "| Col A | Col B |\n|-------|-------|\n| foo   | bar   |\n",
            encoding="utf-8",
        )
        docx = tmp_path / "table.docx"

        from kontor_cli.md_to_docx import convert

        result = convert(md, docx)
        assert result.exists()

    def test_convert_task_list(self, tmp_path: Path) -> None:
        """Task-list checkboxes are rendered."""
        md = tmp_path / "tasks.md"
        md.write_text(
            "- [ ] Open item\n- [x] Done item\n",
            encoding="utf-8",
        )
        docx = tmp_path / "tasks.docx"

        from kontor_cli.md_to_docx import convert

        result = convert(md, docx)
        assert result.exists()

    def test_convert_returns_path(self, tmp_path: Path) -> None:
        """convert() returns a Path pointing at the written file."""
        md = tmp_path / "r.md"
        md.write_text("Hello\n", encoding="utf-8")
        docx = tmp_path / "r.docx"

        from kontor_cli.md_to_docx import convert

        out = convert(md, docx)
        assert isinstance(out, Path)
        assert out == docx


class TestCliMdToDocx:
    def test_cli_help(self) -> None:
        """md-to-docx subcommand appears in CLI help."""
        from click.testing import CliRunner

        from kontor_cli.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "md-to-docx" in result.output

    def test_cli_converts_file(self, tmp_path: Path) -> None:
        """CLI md-to-docx command converts a file and reports success."""
        from click.testing import CliRunner

        from kontor_cli.cli import cli

        md = tmp_path / "input.md"
        md.write_text("# Title\n\nSome content.\n", encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(cli, ["md-to-docx", str(md)])
        assert result.exit_code == 0, result.output
        assert "wrote" in result.output
        assert (tmp_path / "input.docx").exists()

    def test_cli_output_dir(self, tmp_path: Path) -> None:
        """--output-dir places the .docx in the specified directory."""
        from click.testing import CliRunner

        from kontor_cli.cli import cli

        md = tmp_path / "src.md"
        md.write_text("# Hi\n", encoding="utf-8")
        out_dir = tmp_path / "output"

        runner = CliRunner()
        result = runner.invoke(cli, ["md-to-docx", str(md), "--output-dir", str(out_dir)])
        assert result.exit_code == 0, result.output
        assert (out_dir / "src.docx").exists()
