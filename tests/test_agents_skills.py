"""에이전트/skill/문서 파일의 frontmatter와 CLI 참조 검사."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
AGENTS = ["nvme-spec-expert", "ocp-spec-expert", "rule-verifier"]
SKILLS = ["id-validate", "id-rule-extract", "id-rule-fix"]
SUBCOMMANDS = {"collect", "validate", "check-rules", "coverage"}


def frontmatter_text(text: str) -> dict:
    m = re.match(r"---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
    assert m, "frontmatter 없음"
    return yaml.safe_load(m.group(1))


def agent_path(a: str) -> Path:
    return ROOT / ".claude" / "agents" / f"{a}.md"


def skill_path(s: str) -> Path:
    return ROOT / ".claude" / "skills" / s / "SKILL.md"


def read(p: Path) -> str:
    return p.read_text("utf-8")


def test_agent_frontmatter():
    for a in AGENTS:
        fm = frontmatter_text(read(agent_path(a)))
        assert fm["name"] == a and fm["description"] and fm["tools"]


def test_skill_frontmatter_and_cli_refs():
    for s in SKILLS:
        text = read(skill_path(s))
        fm = frontmatter_text(text)
        assert fm["name"] == s and fm["description"]
        assert "uv run idharness" in text


def test_skills_only_reference_existing_subcommands():
    for p in [skill_path(s) for s in SKILLS] + [agent_path(a) for a in AGENTS]:
        for sub in re.findall(r"uv run idharness ([\w-]+)", read(p)):
            assert sub in SUBCOMMANDS, (p, sub)


def test_all_reference_rule_authoring_doc():
    assert (ROOT / "docs" / "rule-authoring.md").is_file()
    assert (ROOT / "docs" / "adding-a-spec.md").is_file()
    for p in [skill_path(s) for s in SKILLS] + [agent_path(a) for a in AGENTS]:
        assert "docs/rule-authoring.md" in read(p), p


def test_files_not_too_long():
    for p in [skill_path(s) for s in SKILLS] + [agent_path(a) for a in AGENTS]:
        assert len(read(p).splitlines()) <= 200, p
