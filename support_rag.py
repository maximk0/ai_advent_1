"""Local retrieval over the product support FAQ."""

from __future__ import annotations

import re
from pathlib import Path

from document_indexer import DocumentIndexer


ROOT = Path(__file__).resolve().parent
FAQ_PATH = ROOT / "docs" / "support" / "faq.md"


def _sections(markdown: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, list[str]]] = []
    title = "FAQ"
    lines: list[str] = []
    for line in markdown.splitlines():
        if re.match(r"^#{1,3}\s+", line):
            if any(value.strip() for value in lines):
                sections.append((title, lines))
            title = re.sub(r"^#{1,3}\s+", "", line).strip()
            lines = [line]
        else:
            lines.append(line)
    if any(value.strip() for value in lines):
        sections.append((title, lines))
    return [(title, "\n".join(lines).strip()) for title, lines in sections]


class SupportKnowledgeBase:
    """Build lightweight FAQ chunks and rank them by normalized term overlap."""

    def __init__(self, faq_path: Path = FAQ_PATH):
        self.faq_path = faq_path

    def build(self) -> list[dict]:
        text = self.faq_path.read_text(encoding="utf-8")
        chunks = []
        for section, content in _sections(text):
            chunks.append({
                "chunk_id": f"support_faq_{len(chunks) + 1:03d}",
                "source": self.faq_path.relative_to(ROOT).as_posix(),
                "title_or_file": self.faq_path.name,
                "section": section,
                "strategy": "support_faq",
                "text": content,
            })
        return chunks

    def search(self, query: str, top_k: int = 4) -> list[dict]:
        original = set(DocumentIndexer._tokens(query))
        rewritten = set(DocumentIndexer._tokens(DocumentIndexer.rewrite_query(query)))
        expanded = rewritten - original
        denominator = len(original) + 0.35 * len(expanded)
        if denominator == 0:
            return []

        ranked = []
        for chunk in self.build():
            terms = set(DocumentIndexer._tokens(chunk["text"]))
            exact_hits = original & terms
            expanded_hits = expanded & terms
            score = (len(exact_hits) + 0.35 * len(expanded_hits)) / denominator
            if score < 0.08:
                continue
            item = dict(chunk)
            item["similarity"] = round(score, 3)
            item["search_score"] = len(exact_hits) + len(expanded_hits)
            item["matched_terms"] = sorted(exact_hits | expanded_hits)
            ranked.append(item)

        ranked.sort(key=lambda item: (item["similarity"], item["search_score"]), reverse=True)
        return ranked[:max(1, min(int(top_k), 8))]
