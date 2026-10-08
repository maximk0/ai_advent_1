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
import math
from pathlib import Path
from typing import Dict, Any, List, Tuple

ROOT_DIR = Path(__file__).resolve().parent
INDEX_FILE = ROOT_DIR / "document_index.json"

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

    def search(
        self,
        query: str,
        strategy: str = "all",
        source_prefix: str | None = None,
    ) -> List[Dict[str, Any]]:
        """Семантический/текстовый поиск по индексу с учетом стратегии."""
        if not INDEX_FILE.exists():
            self.build_index()

        try:
            data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
            all_chunks = data.get("chunks", [])
        except Exception:
            all_chunks = self.chunks

        q_words = set(query.lower().split())
        scored = []

        for c in all_chunks:
            if strategy != "all" and c.get("strategy") != strategy:
                continue
            if source_prefix and not c.get("source", "").startswith(source_prefix):
                continue
            text_lower = c["text"].lower()
            # Простейший подсчет совпадений слов (TF-IDF симуляция)
            score = sum(1 for w in q_words if w in text_lower)
            if score > 0:
                scored.append((score, c))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored[:10]]

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
