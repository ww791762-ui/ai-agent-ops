import hashlib
import io
import zipfile
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, ValidationError


class SkillError(ValueError):
    pass


class SkillMeta(BaseModel):
    id: str
    version: str
    intents: list[str]
    keywords: list[str] = Field(default_factory=list)
    allowed_tools: list[str]
    required_evidence: list[str] = Field(default_factory=list)
    max_steps: int = Field(15, ge=1, le=30)


class Skill(BaseModel):
    meta: SkillMeta
    instructions: str
    md5: str


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2].lstrip()
    return text


def parse_skill_zip(data: bytes, known_tools: set[str]) -> Skill:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            md_name = next((n for n in names if n.endswith("SKILL.md")), None)
            meta_name = next((n for n in names if n.endswith("skill.yaml")), None)
            if not md_name or not meta_name:
                raise SkillError("Skill 包缺少 SKILL.md 或 skill.yaml")
            md_bytes, meta_bytes = zf.read(md_name), zf.read(meta_name)
    except zipfile.BadZipFile as e:
        raise SkillError(f"Skill 包不是合法的 zip: {e}") from e
    try:
        meta = SkillMeta.model_validate(yaml.safe_load(meta_bytes))
    except ValidationError as e:
        raise SkillError(f"skill.yaml 不合法: {e}") from e
    unknown = sorted(set(meta.allowed_tools) - known_tools)
    if unknown:
        raise SkillError(f"allowed_tools 包含未注册的工具: {', '.join(unknown)}")
    return Skill(meta=meta, instructions=_strip_frontmatter(md_bytes.decode("utf-8")),
                 md5=hashlib.md5(meta_bytes + b"\n" + md_bytes).hexdigest())


def build_skill_zip(skill_dir: Path) -> bytes:
    """把一个 Skill 目录打包成 zip，包内路径为 <目录名>/<相对路径>。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(skill_dir.rglob("*")):
            if f.is_file():
                zf.write(f, f"{skill_dir.name}/{f.relative_to(skill_dir).as_posix()}")
    return buf.getvalue()
