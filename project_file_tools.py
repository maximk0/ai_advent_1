"""Bounded read, search and write helpers for the Day 34 project file assistant."""

from __future__ import annotations

import difflib
import hashlib
import re
from pathlib import Path

from document_indexer import DocumentIndexer


ROOT = Path(__file__).resolve().parent
TEXT_SUFFIXES = {".md", ".py", ".html", ".css", ".js", ".json", ".toml", ".yml", ".yaml", ".txt", ".sh"}
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".codex", ".agents", "dist", "build"}
SKIP_NAMES = {".env", ".env.local", "history_day15.json", "history_support.json", "history_project_help.json", "assignments_state.json", "document_index.json", "project_index.json"}
MAX_FILE_BYTES = 256_000
TASK_FILLER = {
    "найди", "место", "места", "используется", "использования", "использован", "укажи", "кратко", "объясни",
    "проверь", "проверить", "сверь", "сверить", "обнови", "обновить", "создай", "создать", "подготовь",
    "задача", "цель", "файл", "файлы", "проект", "проекте", "назначение", "каждого", "все", "всех",
    "текущий", "текущей", "связанные", "содержимое", "сохрани", "разделы", "только", "может", "данным",
}


class ProjectFileError(ValueError):
    """A requested project file operation violates workspace limits."""


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _redact_secrets(text: str) -> str:
    patterns = (
        (re.compile(r"(?i)\b(OPENROUTER_API_KEY|[A-Z0-9_]*(?:API_KEY|ACCESS_TOKEN|PASSWORD|SECRET|PRIVATE_KEY))\s*([:=])\s*([^\s,;]+)"), r"\1\2[СКРЫТО]"),
        (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{16,}"), "Bearer [СКРЫТО]"),
        (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"), "[СКРЫТО]"),
    )
    redacted = text
    for pattern, replacement in patterns:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _safe_file(path: Path) -> bool:
    if not path.is_file() or path.is_symlink() or path.suffix.lower() not in TEXT_SUFFIXES:
        return False
    relative = path.relative_to(ROOT)
    if any(part in SKIP_DIRS for part in relative.parts) or path.name in SKIP_NAMES or path.name.startswith("history_"):
        return False
    if path.name.endswith("_index.json") or path.stat().st_size > MAX_FILE_BYTES:
        return False
    return True


def list_project_files(root: Path = ROOT) -> list[Path]:
    """List readable project text files while excluding secrets and generated state."""
    paths = []
    for path in root.rglob("*"):
        if path.is_symlink():
            continue
        relative = path.relative_to(root)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if any(part.startswith(".") and part != ".github" for part in relative.parts):
            continue
        try:
            if _safe_file(path):
                paths.append(path)
        except OSError:
            continue
    return sorted(paths, key=lambda item: _relative(item).casefold())


def search_project_files(query: str, root: Path = ROOT, max_files: int = 10) -> list[dict]:
    """Rank files from their names and text, returning compact matching line excerpts."""
    literals = list(dict.fromkeys(value.rstrip(".,;:!?") for value in re.findall(r"/[A-Za-z0-9_./-]+", query)))
    terms = list(dict.fromkeys(DocumentIndexer._tokens(query)))
    terms = [term for term in terms if term not in TASK_FILLER]
    terms = [term for term in terms if len(term) > 1][:24]
    ranked: list[dict] = []
    for path in list_project_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        relative = path.relative_to(root).as_posix()
        folded_path = relative.casefold()
        name_hits = sum(2 for term in terms if term in folded_path)
        matched_lines = []
        safe_text = _redact_secrets(text)
        for line_number, line in enumerate(safe_text.splitlines(), 1):
            folded_line = line.casefold()
            literal_hits = [literal for literal in literals if literal.casefold() in folded_line]
            if literals and literal_hits:
                matched_lines.append({"line": line_number, "text": line[:600], "terms": literal_hits, "exact": True})
                continue
            hits = [term for term in terms if term in folded_line]
            if hits and not literals:
                matched_lines.append({"line": line_number, "text": line[:600], "terms": hits})
        matched_terms = {term for item in matched_lines for term in item["terms"]}
        exact_count = sum(bool(item.get("exact")) for item in matched_lines)
        if literals and exact_count:
            matched_lines = [item for item in matched_lines if item.get("exact")]
            matched_terms = {term for item in matched_lines for term in item["terms"]}
            score = 100 + exact_count
        elif literals:
            continue
        else:
            score = name_hits + len(matched_terms) + min(len(matched_lines), 8) * 0.1
        if score <= 0:
            continue
        ranked.append({
            "path": relative,
            "score": round(score, 2),
            "matched_terms": sorted(matched_terms),
            "matches": matched_lines,
            "text": safe_text,
        })
    ranked.sort(key=lambda item: (item["score"], len(item["matched_terms"]), item["path"]), reverse=True)
    return ranked[:max(1, min(max_files, 15))]


def read_project_file(relative_path: str, root: Path = ROOT) -> tuple[str, str]:
    """Read a single allowed text file and return its text plus current content hash."""
    candidate = (root / relative_path).resolve()
    root_resolved = root.resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ProjectFileError("Путь должен находиться внутри папки проекта.")
    try:
        safe = _safe_file(candidate)
    except OSError:
        safe = False
    if not safe:
        raise ProjectFileError("Файл отсутствует, имеет неподдерживаемый формат или исключён из файлового помощника.")
    raw_content = candidate.read_text(encoding="utf-8")
    return _redact_secrets(raw_content), hashlib.sha256(raw_content.encode("utf-8")).hexdigest()


def validate_write_path(relative_path: str, root: Path = ROOT) -> Path:
    """Allow documentation edits in the repository root or docs/ only."""
    normalized = relative_path.strip().replace("\\", "/")
    if not normalized or normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise ProjectFileError("Укажите относительный путь к файлу проекта.")
    if Path(normalized).suffix.lower() not in {".md", ".txt"}:
        raise ProjectFileError("Файловый помощник может сохранять только Markdown- и TXT-документы.")
    if normalized not in {"README.md", "CHANGELOG.md"} and not normalized.startswith("docs/"):
        raise ProjectFileError("Создавать и изменять документы можно только в корне или внутри docs/.")
    target = (root / normalized).resolve()
    root_resolved = root.resolve()
    if root_resolved not in target.parents:
        raise ProjectFileError("Путь должен находиться внутри папки проекта.")
    if any(part in SKIP_DIRS or part.startswith(".") for part in Path(normalized).parts):
        raise ProjectFileError("Скрытые и служебные каталоги недоступны для изменения.")
    if target.exists() and not _safe_file(target):
        raise ProjectFileError("Этот файл исключён из файлового помощника.")
    return target


def make_unified_diff(relative_path: str, before: str, after: str) -> str:
    """Format a reviewable unified diff for the proposed document change."""
    return "\n".join(difflib.unified_diff(
        before.splitlines(), after.splitlines(),
        fromfile=f"a/{relative_path}" if before else "/dev/null",
        tofile=f"b/{relative_path}",
        lineterm="",
    ))
