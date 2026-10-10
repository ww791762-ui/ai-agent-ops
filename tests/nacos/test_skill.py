import pytest

from opsagent.nacos.skill import SkillError, build_skill_zip, parse_skill_zip
from tests.helpers import TOOL_IDS, make_skill_zip

META = {"id": "http_5xx", "version": "1.0.0", "intents": ["troubleshoot"],
        "keywords": ["5xx"], "allowed_tools": ["logs.search"], "max_steps": 15}


def test_parse_ok_strips_frontmatter():
    s = parse_skill_zip(make_skill_zip(META, "---\nname: http_5xx\n---\n# 排查\n步骤"), TOOL_IDS)
    assert s.meta.id == "http_5xx" and s.meta.max_steps == 15
    assert s.instructions.startswith("# 排查")
    assert len(s.md5) == 32


def test_md5_depends_on_content_only():
    a = parse_skill_zip(make_skill_zip(META), TOOL_IDS)
    b = parse_skill_zip(make_skill_zip(META), TOOL_IDS)
    c = parse_skill_zip(make_skill_zip({**META, "version": "1.0.1"}), TOOL_IDS)
    assert a.md5 == b.md5 != c.md5


def test_unknown_tool_rejected():
    with pytest.raises(SkillError, match="shell.exec"):
        parse_skill_zip(make_skill_zip({**META, "allowed_tools": ["shell.exec"]}), TOOL_IDS)


def test_max_steps_over_limit_rejected():
    with pytest.raises(SkillError):
        parse_skill_zip(make_skill_zip({**META, "max_steps": 31}), TOOL_IDS)


def test_missing_skill_yaml_rejected():
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("x/SKILL.md", "# only")
    with pytest.raises(SkillError, match="skill.yaml"):
        parse_skill_zip(buf.getvalue(), TOOL_IDS)


def test_build_skill_zip_roundtrip(tmp_path):
    d = tmp_path / "http_5xx"
    d.mkdir()
    (d / "SKILL.md").write_text("# 排查", encoding="utf-8")
    (d / "skill.yaml").write_text("id: http_5xx\nversion: 1.0.0\nintents: [troubleshoot]\n"
                                  "allowed_tools: [logs.search]\n", encoding="utf-8")
    assert parse_skill_zip(build_skill_zip(d), TOOL_IDS).meta.id == "http_5xx"
