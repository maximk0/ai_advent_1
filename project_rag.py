"""Small structural, lexical RAG index for this repository's own docs and code."""

from __future__ import annotations

import ast
import json
import math
import re
from collections import Counter
from pathlib import Path

from document_indexer import DocumentIndexer

ROOT = Path(__file__).resolve().parent
INDEX_PATH = ROOT / "project_index.json"
MAX_CHUNK_CHARS = 1400
INCLUDED_FILES = (
    "README.md",
    "docs/project_guide.md",
    "main.py",
    "simple_agent.py",
    "document_indexer.py",
    "chat_ui.py",
    "mcp_client.py",
    "mcp_server_git.py",
    "project_rag.py",
    "code_review.py",
    ".github/workflows/ai-code-review.yml",
)


def _split_long_text(text: str, limit: int = MAX_CHUNK_CHARS) -> list[str]:
    text = text.strip()
    chunks: list[str] = []
    while len(text) > limit:
        split_at = text.rfind("\n", 0, limit)
        if split_at < limit // 2:
            split_at = text.rfind(" ", 0, limit)
        if split_at < limit // 2:
            split_at = limit
        chunks.append(text[:split_at].strip())
        text = text[split_at:].strip()
    if text:
        chunks.append(text)
    return chunks


def _markdown_sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, list[str]]] = []
    title = "Введение"
    lines: list[str] = []
    for line in text.splitlines():
        if re.match(r"^#{1,4}\s+", line):
            if any(item.strip() for item in lines):
                sections.append((title, lines))
            title = re.sub(r"^#{1,4}\s+", "", line).strip()
            lines = [line]
        else:
            lines.append(line)
    if any(item.strip() for item in lines):
        sections.append((title, lines))
    return [(name, "\n".join(body).strip()) for name, body in sections]


def _python_sections(text: str) -> list[tuple[str, str]]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return [("Файл", text)]
    lines = text.splitlines()
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    ranges: list[tuple[int, int, str]] = []
    if nodes and nodes[0].lineno > 1:
        ranges.append((1, nodes[0].lineno - 1, "Заголовок модуля"))
    for index, node in enumerate(nodes):
        end = nodes[index + 1].lineno - 1 if index + 1 < len(nodes) else len(lines)
        ranges.append((node.lineno, end, getattr(node, "name", "Блок")))
    if not ranges:
        return [("Файл", text)]
    return [(name, "\n".join(lines[start - 1:end]).strip()) for start, end, name in ranges]


class ProjectKnowledgeBase:
    """Build and query a small index over README, project docs, API code and MCP."""

    def __init__(self, root: Path = ROOT):
        self.root = root
        self.index_path = root / INDEX_PATH.name
        self.data = self.build()
        self._tokenized_chunks = [
            DocumentIndexer._tokens(chunk.get("text", "")) for chunk in self.data["chunks"]
        ]
        self._term_frequencies = [Counter(terms) for terms in self._tokenized_chunks]
        self._document_frequency = Counter(
            token for terms in self._tokenized_chunks for token in set(terms)
        )
        total_documents = max(1, len(self._tokenized_chunks))
        self._document_norms = []
        for frequencies in self._term_frequencies:
            weights = [
                (1 + math.log(count))
                * math.log(1 + (total_documents + 1) / (self._document_frequency[term] + 1))
                for term, count in frequencies.items()
            ]
            self._document_norms.append(math.sqrt(sum(value * value for value in weights)))

    def build(self) -> dict:
        chunks: list[dict] = []
        sources: list[str] = []
        for pattern in INCLUDED_FILES:
            paths = sorted(self.root.glob(pattern))
            for path in paths:
                if not path.is_file():
                    continue
                relative = path.relative_to(self.root).as_posix()
                try:
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                sources.append(relative)
                if path.suffix.lower() == ".md":
                    sections = _markdown_sections(text)
                elif path.suffix.lower() == ".py":
                    sections = _python_sections(text)
                else:
                    sections = [("API и данные", text)]
                for section, body in sections:
                    for part in _split_long_text(body):
                        chunks.append({
                            "chunk_id": f"project_{len(chunks) + 1:04d}",
                            "source": relative,
                            "title_or_file": path.name,
                            "section": section,
                            "strategy": "project_structure",
                            "text": part,
                        })
        result = {
            "index_name": "project_docs_and_code",
            "documents": len(sources),
            "sources": sources,
            "total_chunks": len(chunks),
            "chunks": chunks,
        }
        self.index_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    def search(self, query: str, top_k: int = 4) -> list[dict]:
        original = set(DocumentIndexer._tokens(query))
        rewritten = set(DocumentIndexer._tokens(DocumentIndexer.rewrite_query(query)))
        expanded = rewritten - original
        denominator = len(original) + 0.35 * len(expanded)
        if not denominator:
            return []

        chunks = self.data["chunks"]
        total_documents = max(1, len(self._tokenized_chunks))

        def weight(term: str, frequency: int) -> float:
            inverse_document_frequency = math.log(
                1 + (total_documents + 1) / (self._document_frequency[term] + 1)
            )
            return (1 + math.log(frequency)) * inverse_document_frequency

        query_counts = Counter(rewritten)
        query_vector = {term: weight(term, count) for term, count in query_counts.items()}
        query_norm = math.sqrt(sum(value * value for value in query_vector.values()))
        ranked = []
        for index, (chunk, chunk_tokens) in enumerate(zip(chunks, self._tokenized_chunks)):
            terms = set(chunk_tokens)
            exact_hits = original & terms
            expanded_hits = expanded & terms
            score = (len(exact_hits) + 0.35 * len(expanded_hits)) / denominator
            if score < 0.06:
                continue
            chunk_counts = self._term_frequencies[index]
            chunk_norm = self._document_norms[index]
            dot_product = sum(
                query_vector[term] * weight(term, chunk_counts[term])
                for term in query_vector if term in chunk_counts
            )
            vector_similarity = dot_product / (query_norm * chunk_norm) if query_norm and chunk_norm else 0.0
            item = dict(chunk)
            item["similarity"] = round(score, 3)
            item["vector_similarity"] = round(vector_similarity, 3)
            item["retrieval_score"] = round(0.35 * score + 0.65 * vector_similarity, 3)
            item["search_score"] = len(exact_hits) + len(expanded_hits)
            item["matched_terms"] = sorted(exact_hits | expanded_hits)
            ranked.append(item)
        ranked.sort(key=lambda item: (item["retrieval_score"], item["similarity"], item["search_score"]), reverse=True)
        return ranked[:max(1, min(int(top_k), 10))]
