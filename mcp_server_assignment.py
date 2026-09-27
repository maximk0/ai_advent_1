#!/usr/bin/env python3
"""
MCP Server: Assignment Submission & Branch README Generator
Предоставляет инструменты для управления сдачей домашних заданий курса AI Advent,
отправки комментариев в Google Таблицу и генерации README.md для конкретных веток.
Работает по протоколу MCP JSON-RPC 2.0 через stdio.
"""

import sys
import os
import json
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
STATE_FILE = ROOT_DIR / "assignments_state.json"

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"student": "Студент AI Advent", "assignments": {}}

def _save_state(state: dict):
    try:
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        sys.stderr.write(f"Error saving state: {e}\n")

def get_day_status(day_number: str) -> str:
    """Запрашивает статус сдачи выбранного дня из локального реестра знаний."""
    day_key = str(day_number).strip()
    state = _load_state()
    assignments = state.get("assignments", {})
    day_data = assignments.get(day_key)

    if not day_data:
        return json.dumps({
            "day": day_key,
            "status": "not_started",
            "message": f"Задание для дня {day_key} еще не начиналось."
        }, ensure_ascii=False, indent=2)

    return json.dumps({
        "day": day_key,
        "student": state.get("student", "Студент"),
        "details": day_data
    }, ensure_ascii=False, indent=2)

def submit_code_to_sheets(day_number: str, branch_name: str, code_link: str) -> str:
    """Формирует строгий комментарий с кодом и заносит его в ячейку Google Таблицы."""
    day_key = str(day_number).strip()
    branch = branch_name.strip() or "main"
    link = code_link.strip()

    # Точное соблюдение формата пользователя
    formatted_comment = f"код (ветка {branch}): {link}"

    state = _load_state()
    assignments = state.setdefault("assignments", {})
    day_info = assignments.setdefault(day_key, {})

    day_info["branch_name"] = branch
    day_info["code_link"] = link
    day_info["code_comment"] = formatted_comment
    day_info["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

    if day_info.get("video_link"):
        day_info["status"] = "fully_submitted"
    else:
        day_info["status"] = "code_submitted"

    _save_state(state)

    return json.dumps({
        "status": "success",
        "day": day_key,
        "action": "google_sheets_comment_added",
        "cell_comment": formatted_comment,
        "message": f"✅ Запись коду дня {day_key} внесена в Google Таблицу!"
    }, ensure_ascii=False, indent=2)

def submit_video_to_sheets(day_number: str, video_link: str) -> str:
    """Формирует строгий комментарий с видео и заносит его в ячейку Google Таблицы."""
    day_key = str(day_number).strip()
    link = video_link.strip()

    # Точное соблюдение формата пользователя
    formatted_comment = f"видео: {link}"

    state = _load_state()
    assignments = state.setdefault("assignments", {})
    day_info = assignments.setdefault(day_key, {})

    day_info["video_link"] = link
    day_info["video_comment"] = formatted_comment
    day_info["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")

    if day_info.get("code_link"):
        day_info["status"] = "fully_submitted"
    else:
        day_info["status"] = "video_submitted"

    _save_state(state)

    return json.dumps({
        "status": "success",
        "day": day_key,
        "action": "google_sheets_comment_added",
        "cell_comment": formatted_comment,
        "message": f"✅ Запись по видео дня {day_key} внесена в Google Таблицу!"
    }, ensure_ascii=False, indent=2)

def create_assignment_readme(day_number: str, topic: str, learned_info: str, branch_name: str, code_link: str = "", video_link: str = "") -> str:
    """Генерирует и создает README.md строго для ветки сдачи конкретного дня."""
    day_key = str(day_number).strip()
    branch = branch_name.strip() or f"day{day_key}"

    state = _load_state()
    day_info = state.get("assignments", {}).get(day_key, {})

    final_code_link = code_link.strip() or day_info.get("code_link", "")
    final_video_link = video_link.strip() or day_info.get("video_link", "")

    readme_content = f"""# 🚀 AI Advent — День {day_key}: {topic}

> **Ветка репозитория:** `{branch}`
> **Дата сдачи:** {time.strftime('%Y-%m-%d')}

---

## 🛠 Проделанная работа
- Реализовано задание **{day_key}-го дня** в ветке `{branch}`.
- Написана интеграция с MCP-сервером для отправки данных.

---

## 💡 Новые знания и концепции, изученные за день
{learned_info.strip()}

---

## 🔗 Ссылки для проверки (Google Таблица)
- **Код:** `код (ветка {branch}): {final_code_link or 'в процессе'}`
- **Видео:** `видео: {final_video_link or 'в процессе'}`
"""

    readme_file = ROOT_DIR / "README.md"
    readme_file.write_text(readme_content, encoding="utf-8")

    # Обновляем состояние
    assignments = state.setdefault("assignments", {})
    d_info = assignments.setdefault(day_key, {})
    d_info["topic"] = topic
    d_info["has_readme"] = True
    d_info["branch_name"] = branch
    _save_state(state)

    return json.dumps({
        "status": "success",
        "file_created": "README.md",
        "branch": branch,
        "message": f"✅ Файл README.md для ветки {branch} успешно создан!"
    }, ensure_ascii=False, indent=2)

TOOLS = [
    {
        "name": "get_day_status",
        "description": "Проверяет текущий статус сдачи выбранного дня из реестра (загружены ли код и видео).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "day_number": {"type": "string", "description": "Номер дня курса (например '17')"}
            },
            "required": ["day_number"]
        }
    },
    {
        "name": "submit_code_to_sheets",
        "description": "Формирует и сохраняет комментарий вида 'код (ветка $branch): $link' в Google Таблицу.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "day_number": {"type": "string", "description": "Номер дня курса (например '17')"},
                "branch_name": {"type": "string", "description": "Имя ветки Git (например 'day17')"},
                "code_link": {"type": "string", "description": "Ссылка на исходный код на GitHub"}
            },
            "required": ["day_number", "branch_name", "code_link"]
        }
    },
    {
        "name": "submit_video_to_sheets",
        "description": "Формирует и сохраняет комментарий вида 'видео: $link' в Google Таблицу.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "day_number": {"type": "string", "description": "Номер дня курса (например '17')"},
                "video_link": {"type": "string", "description": "Ссылка на видеозапись с демонстрацией"}
            },
            "required": ["day_number", "video_link"]
        }
    },
    {
        "name": "create_assignment_readme",
        "description": "Генерирует README.md для конкретной ветки с описанием темы дня, проделанной работы и новых изученных концепций.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "day_number": {"type": "string", "description": "Номер дня курса (например '17')"},
                "topic": {"type": "string", "description": "Тема дня (например 'Первый инструмент MCP')"},
                "learned_info": {"type": "string", "description": "Описание новых изученных знаний и концепций"},
                "branch_name": {"type": "string", "description": "Имя текущей ветки"},
                "code_link": {"type": "string", "description": "Ссылка на код (необязательно)"},
                "video_link": {"type": "string", "description": "Ссылка на видео (необязательно)"}
            },
            "required": ["day_number", "topic", "learned_info", "branch_name"]
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
                    "name": "assignment-submission-server",
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
        if tool_name == "get_day_status":
            result_text = get_day_status(arguments.get("day_number", "17"))
        elif tool_name == "submit_code_to_sheets":
            result_text = submit_code_to_sheets(
                arguments.get("day_number", "17"),
                arguments.get("branch_name", "main"),
                arguments.get("code_link", "")
            )
        elif tool_name == "submit_video_to_sheets":
            result_text = submit_video_to_sheets(
                arguments.get("day_number", "17"),
                arguments.get("video_link", "")
            )
        elif tool_name == "create_assignment_readme":
            result_text = create_assignment_readme(
                arguments.get("day_number", "17"),
                arguments.get("topic", "Первый инструмент MCP"),
                arguments.get("learned_info", ""),
                arguments.get("branch_name", "day17"),
                arguments.get("code_link", ""),
                arguments.get("video_link", "")
            )
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
