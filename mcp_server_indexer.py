#!/usr/bin/env python3
"""
MCP Server: Document Indexer & RAG Search
Предоставляет инструменты для построения локального индекса документов проекта,
семантического поиска с метаданными и сравнения стратегий Chunking.
Работает по протоколу MCP JSON-RPC 2.0 через stdio.
"""

from __future__ import annotations

import sys
import os
import json
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
import sys
sys.path.insert(0, str(ROOT_DIR))
from document_indexer import DocumentIndexer

indexer = DocumentIndexer(ROOT_DIR)

def build_document_index() -> str:
    """Запускает полный пайплайн индексации документов проекта по обеим стратегиям."""
    try:
        res = indexer.build_index()
        return json.dumps({
            "status": "success",
            "total_documents": res["total_documents"],
            "total_chunks": res["total_chunks"],
            "strategies": res["strategies"],
            "message": f"✅ Успешно проиндексировано документов: {res['total_documents']} (всего чанков: {res['total_chunks']})"
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)

def search_document_index(query: str, strategy: str = "all") -> str:
    """Выполняет поиск по индексу документов с учетом метаданных и стратегии."""
    try:
        matches = indexer.search(query, strategy)
        return json.dumps({
            "status": "success",
            "query": query,
            "strategy": strategy,
            "matches_count": len(matches),
            "matches": matches
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)

def compare_chunking_strategies() -> str:
    """Возвращает аналитический отчет сравнения Fixed Size и Structural стратегий."""
    try:
        report = indexer.compare_strategies()
        return json.dumps({
            "status": "success",
            "report": report
        }, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)

TOOLS = [
    {
        "name": "build_document_index",
        "description": "Строит локальный поисковый индекс документов проекта (Markdown и Python) с применением 2 стратегий chunking.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "search_document_index",
        "description": "Выполняет поиск по индексу документов с фильтрацией по стратегии и возвращает чанки с метаданными.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Поисковый запрос"},
                "strategy": {"type": "string", "description": "Стратегия ('all', 'fixed_size', 'structural')", "default": "all"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "compare_chunking_strategies",
        "description": "Сравнивает стратегии Fixed Size и Structural chunking по метрикам (количество, размер, плюсы/минусы).",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    }
]

def handle_json_rpc(request_str: str):
    """Обрабатывает входящие JSON-RPC запросы протокола MCP."""
    try:
        req = json.loads(request_str)
    except json.JSONDecodeError:
        return

    req_id = req.get("id")
    method = req.get("method")
    params = req.get("params", {})

    if method == "initialize":
        response = {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "document-indexer-server",
                    "version": "1.0.0"
                }
            }
        }
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()

    elif method == "notifications/initialized":
        pass

    elif method == "tools/list":
        response = {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": TOOLS
            }
        }
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()

    elif method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        result_text = ""
        if tool_name == "build_document_index":
            result_text = build_document_index()
        elif tool_name == "search_document_index":
            result_text = search_document_index(
                arguments.get("query", "mcp"),
                arguments.get("strategy", "all")
            )
        elif tool_name == "compare_chunking_strategies":
            result_text = compare_chunking_strategies()
        else:
            result_text = f"Неизвестный инструмент: {tool_name}"

        response = {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": result_text
                    }
                ]
            }
        }
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()

def main():
    """Основной цикл чтения stdio."""
    for line in sys.stdin:
        line = line.strip()
        if line:
            handle_json_rpc(line)

if __name__ == "__main__":
    main()
