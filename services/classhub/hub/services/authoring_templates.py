"""Generate teacher authoring templates in Markdown and DOCX."""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape


CONTENT_TYPES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>
"""

PACKAGE_RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship
    Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    Target="word/document.xml"
  />
</Relationships>
"""

DOCUMENT_RELS_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>
"""


@dataclass(frozen=True)
class AuthoringTemplateResult:
    teacher_plan_md_path: Path
    teacher_plan_docx_path: Path
    public_overview_md_path: Path
    public_overview_docx_path: Path

    @property
    def output_paths(self) -> list[Path]:
        return [
            self.teacher_plan_md_path,
            self.teacher_plan_docx_path,
            self.public_overview_md_path,
            self.public_overview_docx_path,
        ]


def slug_to_title(slug: str) -> str:
    parts = [part for part in re.split(r"[-_]+", slug.strip()) if part]
    if not parts:
        return "New Course"
    return " ".join(part.capitalize() for part in parts)


def _session_block(session_num: int) -> str:
    return f"""# Session {session_num:02d}: Session {session_num:02d} Title

Mission: <what students should build or demonstrate>
Lesson slug example: s{session_num:02d}-session-{session_num:02d}-title

Teacher prep
- <what to set up before class starts>

Materials
- <hardware, accounts, files, handouts>

Agenda
- 0-10 min: <intro/check-in>
- 10-45 min: <build time>
- 45-60 min: <share/feedback>

Checkpoints
- <objective signal that students are on track>

Common stuck points + fixes
- <stuck point> -> <fix>

Extensions
- <optional stretch for early finishers>
"""


def teacher_plan_markdown(slug: str, title: str, sessions: int, duration: int, age_band: str) -> str:
    lines = [
        f"# Teacher Session Plan Template: {title}",
        "",
        f"Course slug: {slug}",
        f"Grade level: {age_band}",
        f"Session length: {duration} minutes",
        f"Total sessions: {sessions}",
        "",
        "Use `Session NN: Title` headings exactly so `scripts/ingest_syllabus_md.py` can parse this file.",
        "",
    ]
    for idx in range(1, sessions + 1):
        lines.append(_session_block(idx).strip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def public_overview_markdown(slug: str, title: str, sessions: int, duration: int, age_band: str) -> str:
    meeting_time = f"{duration} minutes/week for {sessions} weeks"
    lines = [
        f"# {title}",
        "",
        f"Course slug: {slug}",
        f"Grade level: {age_band}",
        f"Meeting time: {meeting_time}",
        "Platform: <platform/tool name>",
        "",
        "## Course summary",
        "- <1-2 sentence summary for parents/admin>",
        "",
        "## Learning goals",
        "- <goal 1>",
        "- <goal 2>",
        "",
        "## Student outputs",
        "- <what students submit or present>",
        "",
        "## Materials and prerequisites",
        "- <required accounts/devices or setup>",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _docx_document_xml(text: str) -> str:
    paragraphs = []
    for raw_line in text.splitlines():
        if not raw_line:
            paragraphs.append("<w:p/>")
            continue
        attrs = ' xml:space="preserve"' if raw_line != raw_line.strip() else ""
        paragraphs.append(f"<w:p><w:r><w:t{attrs}>{escape(raw_line)}</w:t></w:r></w:p>")

    paragraph_xml = "".join(paragraphs)
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    {paragraph_xml}
    <w:sectPr>
      <w:pgSz w:w="12240" w:h="15840"/>
      <w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" w:header="720" w:footer="720" w:gutter="0"/>
    </w:sectPr>
  </w:body>
</w:document>
"""


def _write_docx(path: Path, text: str) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
        zf.writestr("_rels/.rels", PACKAGE_RELS_XML)
        zf.writestr("word/_rels/document.xml.rels", DOCUMENT_RELS_XML)
        zf.writestr("word/document.xml", _docx_document_xml(text))


def _validate_output_paths(paths: list[Path], overwrite: bool) -> None:
    if overwrite:
        return
    existing = [path for path in paths if path.exists()]
    if existing:
        joined = ", ".join(str(path) for path in existing)
        raise ValueError(f"Refusing to overwrite existing files: {joined}")


def generate_authoring_templates(
    *,
    slug: str,
    title: str,
    sessions: int,
    duration: int,
    age_band: str,
    out_dir: Path,
    overwrite: bool = False,
) -> AuthoringTemplateResult:
    if sessions <= 0:
        raise ValueError("sessions must be greater than 0")
    if duration <= 0:
        raise ValueError("duration must be greater than 0")

    normalized_slug = slug.strip()
    normalized_title = (title or slug_to_title(normalized_slug)).strip()
    out_dir.mkdir(parents=True, exist_ok=True)

    teacher_plan_md = teacher_plan_markdown(normalized_slug, normalized_title, sessions, duration, age_band)
    public_overview_md = public_overview_markdown(normalized_slug, normalized_title, sessions, duration, age_band)

    result = AuthoringTemplateResult(
        teacher_plan_md_path=out_dir / f"{normalized_slug}-teacher-plan-template.md",
        teacher_plan_docx_path=out_dir / f"{normalized_slug}-teacher-plan-template.docx",
        public_overview_md_path=out_dir / f"{normalized_slug}-public-overview-template.md",
        public_overview_docx_path=out_dir / f"{normalized_slug}-public-overview-template.docx",
    )
    _validate_output_paths(result.output_paths, overwrite=overwrite)

    result.teacher_plan_md_path.write_text(teacher_plan_md, encoding="utf-8")
    _write_docx(result.teacher_plan_docx_path, teacher_plan_md)
    result.public_overview_md_path.write_text(public_overview_md, encoding="utf-8")
    _write_docx(result.public_overview_docx_path, public_overview_md)
    return result
