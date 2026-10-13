#!/usr/bin/env python3
"""
Document Indexer & Chunking Strategy Comparator
Реализует загрузку корпуса документов проекта (>30 страниц текста в сумме),
две стратегии разбиения (Fixed Size vs Structural Chunking), добавление метаданных,
генерацию векторного индекса (TF-IDF симуляция) и сохранение в document_index.json.
"""

from __future__ import annotations

import json
import re
import copy
from pathlib import Path
from typing import Dict, Any, List, Tuple

ROOT_DIR = Path(__file__).resolve().parent
INDEX_FILE = ROOT_DIR / "document_index.json"

_STOP_WORDS = {
    "а", "без", "бы", "в", "во", "вот", "все", "всего", "для", "до", "же", "за",
    "и", "из", "или", "как", "к", "ко", "ли", "мне", "на", "над", "не", "ни",
    "но", "о", "об", "от", "по", "под", "при", "про", "с", "со", "так", "то",
    "у", "что", "это", "этот", "эта", "эти", "я", "он", "она", "они", "мы",
    "где", "когда", "кто", "какой", "какая", "какие", "каков", "сколько", "его", "ее",
    "находи", "иметь", "быть", "можно", "нужно",
}
_WORD_RE = re.compile(r"[a-zа-яё0-9]+(?:[-_][a-zа-яё0-9]+)*|\d+(?:[.,]\d+)?", re.IGNORECASE)
_RU_SUFFIXES = (
    "иями", "ями", "ами", "ываются", "иваются", "аются", "яются", "утся", "ются", "ется",
    "иться", "аться", "ого", "ему", "ому", "ыми", "ими", "ая", "яя", "ое", "ее",
    "ые", "ие", "ый", "ий", "ой", "ую", "юю", "ого", "его", "ому", "ему", "ах",
    "ях", "ам", "ям", "ом", "ем", "ой", "ей", "ать", "ять", "ить", "еть", "ться",
    "тся", "ть", "ы", "и", "а", "я", "у", "ю", "е",
)
_SYNONYMS = {
    "отказ": ("неисправность", "поломка"),
    "датчик": ("сенсор",),
    "температур": ("нагрев", "тепло"),
    "дежурн": ("оператор",),
    "показан": ("измерение", "замер"),
    "иск": ("найти", "поиск"),
}

class DocumentIndexer:
    def __init__(self, root_dir: Path = ROOT_DIR):
        self.root_dir = root_dir
        self.documents: List[Dict[str, Any]] = []
        self.chunks: List[Dict[str, Any]] = []

    def load_corpus(self) -> List[Dict[str, Any]]:
        """Загружает корпус документов проекта (.md и .py файлы)."""
        docs = []
        for path in self.root_dir.rglob("*"):
            if path.is_file() and path.suffix in [".md", ".py"] and ".git" not in path.parts and ".venv" not in path.parts:
                try:
                    content = path.read_text(encoding="utf-8")
                    if len(content.strip()) > 50:
                        docs.append({
                            "source": str(path.relative_to(self.root_dir)),
                            "title": path.name,
                            "type": path.suffix.lstrip("."),
                            "content": content
                        })
                except Exception:
                    pass
        self.documents = docs
        return docs

    def chunk_fixed_size(self, chunk_size: int = 600, overlap: int = 60) -> List[Dict[str, Any]]:
        """Стратегия 1: Разбиение по фиксированному размеру символов с перекрытием."""
        fixed_chunks = []
        chunk_counter = 1

        for doc in self.documents:
            text = doc["content"]
            source = doc["source"]
            title = doc["title"]

            length = len(text)
            start = 0
            while start < length:
                end = min(start + chunk_size, length)
                chunk_text = text[start:end]

                chunk = {
                    "chunk_id": f"fix_{chunk_counter:04d}",
                    "source": source,
                    "title_or_file": title,
                    "section": f"Chars {start}-{end}",
                    "strategy": "fixed_size",
                    "text": chunk_text,
                    "word_count": len(chunk_text.split())
                }
                fixed_chunks.append(chunk)
                chunk_counter += 1
                start += (chunk_size - overlap)

        return fixed_chunks

    def chunk_structural(self) -> List[Dict[str, Any]]:
        """Стратегия 2: Структурное/семантическое разбиение (по заголовкам Markdown и классам/функциям Python)."""
        struct_chunks = []
        chunk_counter = 1

        for doc in self.documents:
            text = doc["content"]
            source = doc["source"]
            title = doc["title"]
            doc_type = doc["type"]

            if doc_type == "md":
                # Разбиваем по заголовкам Markdown (#, ##, ###)
                sections = re.split(r'(?m)^(#{1,3}\s+.+)', text)
                current_section = "Introduction"
                current_text = ""

                for part in sections:
                    part_stripped = part.strip()
                    if part_stripped.startswith("#"):
                        if current_text.strip():
                            chunk = {
                                "chunk_id": f"str_{chunk_counter:04d}",
                                "source": source,
                                "title_or_file": title,
                                "section": current_section,
                                "strategy": "structural",
                                "text": current_text.strip(),
                                "word_count": len(current_text.split())
                            }
                            struct_chunks.append(chunk)
                            chunk_counter += 1
                        current_section = part_stripped.lstrip("#").strip()
                        current_text = ""
                    else:
                        current_text += part + "\n"

                if current_text.strip():
                    chunk = {
                        "chunk_id": f"str_{chunk_counter:04d}",
                        "source": source,
                        "title_or_file": title,
                        "section": current_section,
                        "strategy": "structural",
                        "text": current_text.strip(),
                        "word_count": len(current_text.split())
                    }
                    struct_chunks.append(chunk)
                    chunk_counter += 1

            elif doc_type == "py":
                # Разбиваем по функциям def и классам class в Python
                lines = text.splitlines()
                current_section = "Module Header"
                current_lines = []

                for line in lines:
                    if line.startswith("def ") or line.startswith("class "):
                        if current_lines:
                            block_text = "\n".join(current_lines)
                            if block_text.strip():
                                chunk = {
                                    "chunk_id": f"str_{chunk_counter:04d}",
                                    "source": source,
                                    "title_or_file": title,
                                    "section": current_section,
                                    "strategy": "structural",
                                    "text": block_text.strip(),
                                    "word_count": len(block_text.split())
                                }
                                struct_chunks.append(chunk)
                                chunk_counter += 1
                        current_section = line.strip()
                        current_lines = [line]
                    else:
                        current_lines.append(line)

                if current_lines:
                    block_text = "\n".join(current_lines)
                    if block_text.strip():
                        chunk = {
                            "chunk_id": f"str_{chunk_counter:04d}",
                            "source": source,
                            "title_or_file": title,
                            "section": current_section,
                            "strategy": "structural",
                            "text": block_text.strip(),
                            "word_count": len(block_text.split())
                        }
                        struct_chunks.append(chunk)
                        chunk_counter += 1

        return struct_chunks

    def build_index(self) -> Dict[str, Any]:
        """Строит полный индекс, применяя обе стратегии chunking."""
        self.load_corpus()
        fix_chunks = self.chunk_fixed_size()
        str_chunks = self.chunk_structural()
        self.chunks = fix_chunks + str_chunks

        index_data = {
            "total_documents": len(self.documents),
            "total_chunks": len(self.chunks),
            "strategies": {
                "fixed_size": {
                    "count": len(fix_chunks),
                    "avg_word_count": sum(c["word_count"] for c in fix_chunks) / max(1, len(fix_chunks))
                },
                "structural": {
                    "count": len(str_chunks),
                    "avg_word_count": sum(c["word_count"] for c in str_chunks) / max(1, len(str_chunks))
                }
            },
            "chunks": self.chunks
        }

        INDEX_FILE.write_text(json.dumps(index_data, ensure_ascii=False, indent=2), encoding="utf-8")
        return index_data

    @staticmethod
    def _normalize_token(token: str) -> str:
        token = token.casefold().replace("ё", "е").replace("_", "-")
        # Treat punctuation variants such as T-4 and T4 as the same identifier.
        token = token.replace("-", "")
        if re.search(r"[а-я]", token):
            for suffix in _RU_SUFFIXES:
                if len(token) - len(suffix) >= 3 and token.endswith(suffix):
                    token = token[:-len(suffix)]
                    break
        return token

    @classmethod
    def _tokens(cls, text: str, remove_stop_words: bool = True) -> list[str]:
        tokens = [cls._normalize_token(token) for token in _WORD_RE.findall(text or "")]
        if remove_stop_words:
            tokens = [token for token in tokens if token not in _STOP_WORDS and len(token) > 1]
        return tokens

    @classmethod
    def rewrite_query(cls, query: str) -> str:
        """Deterministically normalize a question and add a small set of domain synonyms."""
        original = [token.casefold().replace("ё", "е") for token in _WORD_RE.findall(query or "")]
        original = [token for token in original if cls._normalize_token(token) not in _STOP_WORDS]
        expanded = list(original)
        for token in original:
            expanded.extend(_SYNONYMS.get(cls._normalize_token(token), ()))
        return " ".join(dict.fromkeys(expanded))

    def _load_chunks(self) -> list[dict[str, Any]]:
        if not INDEX_FILE.exists():
            self.build_index()
        try:
            data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
            return data.get("chunks", [])
        except Exception:
            return self.chunks

    def _rank(
        self,
        query: str,
        source_prefix: str | None = None,
        limit: int = 10,
        strategy: str = "all",
    ) -> list[dict[str, Any]]:
        query_terms = set(self._tokens(query))
        if not query_terms:
            return []
        ranked = []
        for chunk in self._load_chunks():
            if strategy != "all" and chunk.get("strategy") != strategy:
                continue
            if source_prefix and not chunk.get("source", "").startswith(source_prefix):
                continue
            terms = set(self._tokens(chunk.get("text", "")))
            matched = query_terms & terms
            if matched:
                item = copy.deepcopy(chunk)
                item["search_score"] = len(matched)
                item["matched_terms"] = sorted(matched)
                ranked.append(item)
        ranked.sort(key=lambda item: item["search_score"], reverse=True)
        return ranked[:max(0, int(limit))]

    def compare_retrieval(
        self,
        query: str,
        source_prefix: str | None = None,
        top_k_before: int = 10,
        top_k_after: int = 3,
        similarity_threshold: float = 0.25,
        query_rewrite_enabled: bool = True,
    ) -> dict[str, Any]:
        """Return a baseline and a filtered/reranked result using comparable candidate limits."""
        top_k_before = max(1, min(int(top_k_before), 50))
        top_k_after = max(1, min(int(top_k_after), top_k_before))
        similarity_threshold = max(0.0, min(float(similarity_threshold), 1.0))

        rewritten_query = self.rewrite_query(query) if query_rewrite_enabled else query
        baseline_candidates = self._rank(query, source_prefix, top_k_before)
        rewritten_candidates = (
            self._rank(rewritten_query, source_prefix, top_k_before)
            if query_rewrite_enabled else copy.deepcopy(baseline_candidates)
        )
        query_terms = set(self._tokens(query))
        rewritten_terms = set(self._tokens(rewritten_query))
        expanded_terms = rewritten_terms - query_terms

        filtered = []
        for candidate in rewritten_candidates:
            chunk_terms = set(self._tokens(candidate.get("text", "")))
            original_hits = query_terms & chunk_terms
            expanded_hits = expanded_terms & chunk_terms
            # Exact question concepts carry more weight than added synonyms.
            denominator = len(query_terms) + 0.35 * len(expanded_terms)
            weighted_hits = len(original_hits) + 0.35 * len(expanded_hits)
            similarity = weighted_hits / denominator if denominator else 0.0
            candidate["similarity"] = round(similarity, 3)
            candidate["matched_terms"] = sorted(original_hits | expanded_hits)
            if similarity >= similarity_threshold:
                filtered.append(candidate)
        filtered.sort(key=lambda item: (item["similarity"], item["search_score"]), reverse=True)
        passed_threshold_count = len(filtered)
        dropped_by_threshold_count = len(rewritten_candidates) - passed_threshold_count
        trimmed_by_top_k_count = max(0, passed_threshold_count - top_k_after)

        return {
            "original_query": query,
            "rewritten_query": rewritten_query,
            "query_rewrite_enabled": query_rewrite_enabled,
            "top_k_before": top_k_before,
            "top_k_after": top_k_after,
            "similarity_threshold": similarity_threshold,
            "baseline_candidates": baseline_candidates,
            "baseline_results": baseline_candidates[:top_k_after],
            "candidates_before_filter": rewritten_candidates,
            "passed_threshold_count": passed_threshold_count,
            "dropped_by_threshold_count": dropped_by_threshold_count,
            "trimmed_by_top_k_count": trimmed_by_top_k_count,
            "filtered_results": filtered[:top_k_after],
        }

    def search(
        self,
        query: str,
        strategy: str = "all",
        source_prefix: str | None = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Return lexical matches ranked by normalized meaningful-token overlap."""
        return self._rank(query, source_prefix, limit=max(0, int(limit)), strategy=strategy)

    def compare_strategies(self) -> Dict[str, Any]:
        """Возвращает детальный отчет сравнения Fixed Size и Structural стратегий."""
        if not INDEX_FILE.exists():
            self.build_index()

        data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        fix_c = [c for c in data["chunks"] if c["strategy"] == "fixed_size"]
        str_c = [c for c in data["chunks"] if c["strategy"] == "structural"]

        def stats(lst):
            if not lst:
                return {"count": 0, "avg_words": 0, "min_words": 0, "max_words": 0}
            counts = [c["word_count"] for c in lst]
            return {
                "count": len(lst),
                "avg_words": round(sum(counts) / len(counts), 1),
                "min_words": min(counts),
                "max_words": max(counts)
            }

        return {
            "total_documents_indexed": data["total_documents"],
            "comparison": {
                "fixed_size_strategy": {
                    "description": "Разбиение блоков текста строго по фиксированному числу символов с перекрытием (overlap).",
                    "metrics": stats(fix_c),
                    "pros": ["Равномерный размер чанков", "Простота реализации"],
                    "cons": ["Может разрывать предложения и смысловые блоки посередине"]
                },
                "structural_strategy": {
                    "description": "Интеллектуальное разбиение по границам структуры документов (заголовки Markdown, функции и классы Python).",
                    "metrics": stats(str_c),
                    "pros": ["Сохраняет целостность логических блоков и функций", "Лучший контекст для RAG"],
                    "cons": ["Разбросанный размер чанков (от коротких до длинных методов)"]
                }
            }
        }

if __name__ == "__main__":
    indexer = DocumentIndexer()
    res = indexer.build_index()
    print(f"Indexed {res['total_documents']} documents into {res['total_chunks']} chunks.")
