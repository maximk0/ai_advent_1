#!/usr/bin/env python3
"""
MCP Server: Project Inspector
Предоставляет инструменты для анализа структуры проекта, файлов и окружения.
Работает по стандартному протоколу MCP JSON-RPC через stdio.
"""

import sys
import os
import json
import pkg_resources
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent

def list_project_files(path: str = ".") -> str:
    """Возвращает список файлов и директорий проекта."""
    target_dir = (ROOT_DIR / path).resolve()
    if not str(target_dir).startswith(str(ROOT_DIR)):
        return json.dumps({"error": "Доступ за пределы директории проекта запрещен."})

    if not target_dir.exists():
        return json.dumps({"error": f"Путь {path} не существует."})

    items = []
    for entry in target_dir.iterdir():
        if entry.name.startswith("."):
            continue
        items.append({
            "name": entry.name,
            "type": "directory" if entry.is_dir() else "file",
            "size_bytes": entry.stat().st_size if entry.is_file() else 0
        })
    return json.dumps({"path": str(target_dir), "items": items}, ensure_ascii=False, indent=2)

def check_dependencies(package_name: str = "") -> str:
    """Проверяет установленные Python-пакеты в текущем окружении."""
    installed = [f"{d.project_name}=={d.version}" for d in pkg_resources.working_set]
    installed.sort()

    if package_name:
        matched = [pkg for pkg in installed if package_name.lower() in pkg.lower()]
        return json.dumps({"search": package_name, "found": matched}, ensure_ascii=False, indent=2)

    return json.dumps({"total_packages": len(installed), "packages": installed[:30], "note": "Показаны первые 30 пакетов"}, ensure_ascii=False, indent=2)

def read_project_file(filename: str) -> str:
    """Читает содержимое файла из директории проекта."""
    target_file = (ROOT_DIR / filename).resolve()
    if not str(target_file).startswith(str(ROOT_DIR)):
        return "Ошибка: Доступ за пределы директории проекта запрещен."
    if not target_file.exists():
        return f"Ошибка: Файл {filename} не найден."
    if not target_file.is_file():
        return f"Ошибка: {filename} не является файлом."

    try:
        content = target_file.read_text(encoding="utf-8")
        if len(content) > 5000:
            content = content[:5000] + "\n... [содержимое обрезано до 5000 символов]"
        return content
    except Exception as e:
        return f"Ошибка при чтении файла: {e}"

TOOLS = [
    {
        "name": "list_project_files",
        "description": "Возвращает список файлов и директорий проекта.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Относительный путь к директории (по умолчанию '.')", "default": "."}
            }
        }
    },
    {
        "name": "check_dependencies",
        "description": "Проверяет установленные Python-пакеты в виртуальном или системном окружении.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "package_name": {"type": "string", "description": "Название пакета для поиска (необязательно)"}
            }
        }
    },
    {
        "name": "read_project_file",
        "description": "Читает текстовое содержимое файла из директории проекта.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Имя или относительный путь к файлу"}
            },
            "required": ["filename"]
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
                    "name": "project-inspector",
                    "version": "1.0.0"
                }
            }
        }
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()

    elif method == "notifications/initialized":
        pass  # Уведомление об инициализации, ответ не требуется

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
        if tool_name == "list_project_files":
            path = arguments.get("path", ".")
            result_text = list_project_files(path)
        elif tool_name == "check_dependencies":
            pkg = arguments.get("package_name", "")
            result_text = check_dependencies(pkg)
        elif tool_name == "read_project_file":
            fname = arguments.get("filename", "")
            result_text = read_project_file(fname)
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
