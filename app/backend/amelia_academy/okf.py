"""Open Knowledge Format (OKF v0.2) bundles: write and check.

A bundle is a directory of markdown concepts with YAML frontmatter, plus the reserved
`index.md` (directory listing, spec §8) and `log.md` (update history, spec §9).

Frontmatter is written as one `key: <JSON>` line per key. JSON values are valid YAML, so any
YAML reader parses the file, and this module can read back what it wrote without a YAML
dependency. The reader is only meant for bundles this module produced.
"""

import json
import re
import shutil
import tempfile
import unicodedata
from pathlib import Path

OKF_VERSION = "0.2"
RESERVED = ("index.md", "log.md")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
_KEY_ORDER = ("type", "title", "description", "resource", "tags", "status", "sources", "generated", "verified")


def slugify(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")[:80] or "concept"


def frontmatter(meta: dict) -> str:
    if not str(meta.get("type") or "").strip():
        raise ValueError("an OKF concept needs a non-empty type")
    keys = [k for k in _KEY_ORDER if k in meta] + sorted(k for k in meta if k not in _KEY_ORDER)
    lines = [f"{k}: {json.dumps(meta[k], ensure_ascii=False)}" for k in keys if meta[k] not in (None, [], "")]
    return "---\n" + "\n".join(lines) + "\n---\n"


def concept(meta: dict, body: str) -> str:
    return frontmatter(meta) + "\n" + body.strip() + "\n"


def parse(text: str) -> tuple[dict, str]:
    """Split a concept written by `concept` into (frontmatter, body). Raises ValueError when malformed."""
    if not text.startswith("---\n"):
        raise ValueError("missing frontmatter opening '---'")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("missing frontmatter closing '---'")
    meta = {}
    for line in text[4:end].splitlines():
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        if not sep or not key.strip() or key != key.strip():
            raise ValueError(f"unparseable frontmatter line: {line[:60]!r}")
        try:
            meta[key] = json.loads(value.strip())
        except json.JSONDecodeError:
            meta[key] = value.strip()
    return meta, text[end + 5:]


def index(sections: list[tuple[str, list[tuple[str, str, str]]]], *, root: bool = False) -> str:
    """sections: [(heading, [(title, link, description)])]. Only the bundle-root index carries frontmatter."""
    out = [f"---\nokf_version: \"{OKF_VERSION}\"\n---\n"] if root else []
    for heading, entries in sections:
        if not entries:
            continue
        out.append(f"# {heading}\n")
        out += [f"* [{title}]({link})" + (f" - {desc}" if desc else "") for title, link, desc in entries]
        out.append("")
    return "\n".join(out).strip() + "\n"


def log(entries: list[tuple[str, str, str]]) -> str:
    """entries: [(YYYY-MM-DD, bold word, prose)], any order; written newest first, grouped by date."""
    out = ["# Bundle Update Log", ""]
    by_day: dict[str, list[str]] = {}
    for day, word, prose in entries:
        by_day.setdefault(day, []).append(f"* **{word}**: {prose}")
    for day in sorted(by_day, reverse=True):
        out += [f"## {day}", *by_day[day], ""]
    return "\n".join(out).strip() + "\n"


def write_bundle(root: Path, files: dict[str, str]) -> Path:
    """Replace `root` with exactly `files` (bundle-relative path -> text). The swap happens after a full write."""
    root = Path(root)
    root.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{root.name}-", dir=root.parent))
    try:
        for rel, text in files.items():
            target = (staging / rel).resolve()
            if not target.is_relative_to(staging.resolve()):
                raise ValueError(f"bundle path escapes the bundle: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        if root.exists():
            shutil.rmtree(root)
        staging.rename(root)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return root


def validate(files: dict[str, str]) -> list[str]:
    """Conformance problems (spec §11) of a bundle given as {relative path: text}. Empty means conformant."""
    problems = []
    for rel, text in sorted(files.items()):
        if not rel.endswith(".md"):
            continue
        name = rel.rsplit("/", 1)[-1]
        if name == "index.md":
            body = text
            if text.startswith("---\n"):
                if "/" in rel:
                    problems.append(f"{rel}: only the bundle-root index.md may carry frontmatter")
                try:
                    meta, body = parse(text)
                except ValueError as exc:
                    problems.append(f"{rel}: {exc}")
                    continue
                if set(meta) - {"okf_version"}:
                    problems.append(f"{rel}: index frontmatter may only hold okf_version")
            for line in body.splitlines():
                if line.strip() and not line.startswith(("# ", "* ", "- ")):
                    problems.append(f"{rel}: index lines must be headings or list entries")
                    break
        elif name == "log.md":
            for line in text.splitlines():
                if line.startswith("## ") and not re.fullmatch(r"## \d{4}-\d{2}-\d{2}", line.strip()):
                    problems.append(f"{rel}: log date headings must be YYYY-MM-DD")
        else:
            try:
                meta, _ = parse(text)
            except ValueError as exc:
                problems.append(f"{rel}: {exc}")
                continue
            if not str(meta.get("type") or "").strip():
                problems.append(f"{rel}: frontmatter has no type")
            if meta.get("status") not in (None, "draft", "stable", "deprecated"):
                problems.append(f"{rel}: status must be draft, stable or deprecated")
    return problems


def read_bundle(root: Path) -> dict[str, str]:
    root = Path(root)
    return {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8") for p in sorted(root.rglob("*.md"))}
