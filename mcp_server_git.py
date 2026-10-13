#!/usr/bin/env python3
"""
MCP Server: Targeted Git Manager & Assignment Submission
Предоставляет инструменты для точечного добавления файлов в Git (без git add .),
создания веток, коммитов, настоящего git push на GitHub, генерации README.md ветки
и форматирования комментариев сдачи с кнопками копирования.
Работает по протоколу MCP JSON-RPC 2.0 через stdio.
"""

from __future__ import annotations

import sys
import os
import json
import subprocess
import time
from pathlib import Path
from typing import Union, List, Tuple

ROOT_DIR = Path(__file__).resolve().parent
STATE_FILE = ROOT_DIR / "assignments_state.json"

def _run_git_cmd(args: List[str]) -> Tuple[int, str, str]:
    """Выполняет команду git в директории проекта."""
    try:
        res = subprocess.run(
            ["git"] + args,
            cwd=str(ROOT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except Exception as e:
        return 1, "", str(e)

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

def git_status_check() -> str:
    """Проверяет текущую ветку Git, статус измененных файлов и готовность к коммиту."""
    code_b, current_branch, err_b = _run_git_cmd(["branch", "--show-current"])
    if code_b != 0 or not current_branch:
        code_b2, current_branch, _ = _run_git_cmd(["rev-parse", "--abbrev-ref", "HEAD"])
        if code_b2 != 0:
            current_branch = "unknown"

    code_s, status_out, err_s = _run_git_cmd(["status", "--porcelain"])

    modified_files = []
    if status_out:
        for line in status_out.splitlines():
            line = line.strip()
            if line:
                modified_files.append(line)

    return json.dumps({
        "current_branch": current_branch,
        "has_uncommitted_changes": len(modified_files) > 0,
        "modified_files_count": len(modified_files),
        "modified_files": modified_files[:20],
        "message": f"Текущая ветка: {current_branch}. Измененных файлов: {len(modified_files)}"
    }, ensure_ascii=False, indent=2)

def git_commit_and_push(branch_name: str, target_files: Union[List[str], str], commit_message: str = "") -> str:
    """Выполняет ТОЧЕЧНЫЙ git add выбранных файлов, создает коммит и делает настоящий git push на GitHub."""
    target_branch = branch_name.strip() or "main"
    msg = commit_message.strip() or f"AI Advent submission for branch {target_branch}"

    # Парсим список файлов (может быть передан массивом или строкой через запятую)
    if isinstance(target_files, str):
        files_list = [f.strip() for f in target_files.split(",") if f.strip()]
    else:
        files_list = [str(f).strip() for f in target_files if str(f).strip()]

    if not files_list:
        files_list = ["day17.py", "mcp_server_git.py", "README.md"]

    log_steps = []

    # 1. Переключаем / создаем целевую ветку
    c_code, c_out, c_err = _run_git_cmd(["checkout", "-B", target_branch])
    log_steps.append(f"git checkout -B {target_branch}: {c_out or c_err}")

    # 2. ТОЧЕЧНЫЙ add только выбранных файлов (БЕЗ git add .)
    staged_files = []
    for f_path in files_list:
        full_p = ROOT_DIR / f_path
        if full_p.exists():
            a_code, a_out, a_err = _run_git_cmd(["add", f_path])
            if a_code == 0:
                staged_files.append(f_path)
                log_steps.append(f"git add {f_path}: ok")
            else:
                log_steps.append(f"git add {f_path} warning: {a_err}")
        else:
            log_steps.append(f"file not found for git add: {f_path}")

    # 3. Проверяем, появились ли скоммичиваемые изменения в индексе
    code_s, status_staged, _ = _run_git_cmd(["status", "--porcelain"])

    commit_created = False
    if status_staged:
        m_code, m_out, m_err = _run_git_cmd(["commit", "-m", msg])
        if m_code == 0:
            commit_created = True
            log_steps.append(f"git commit -m '{msg}': {m_out or m_err}")
        else:
            log_steps.append(f"git commit warning: {m_err or m_out}")
    else:
        log_steps.append("git commit: Нечего коммитить (выбранные файлы уже зафиксированы)")

    # 4. Настоящий push на GitHub
    p_code, p_out, p_err = _run_git_cmd(["push", "-u", "origin", target_branch])
    push_msg = p_out or p_err or "Up to date"
    log_steps.append(f"git push -u origin {target_branch}: {push_msg}")

    if commit_created:
        msg_result = f"✅ Точечно скоммичено файлов ({len(staged_files)}) и отправлено в ветку '{target_branch}' на GitHub!"
    elif p_code == 0:
        msg_result = f"ℹ️ Ветка '{target_branch}' синхронизирована с GitHub ({push_msg}). Выбранные файлы не требовали нового коммита."
    else:
        msg_result = f"⚠️ Ветка '{target_branch}': git push вернул {push_msg}"

    return json.dumps({
        "status": "success" if p_code == 0 else "push_warning",
        "branch": target_branch,
        "staged_files": staged_files,
        "commit_created": commit_created,
        "git_push_output": push_msg,
        "log_steps": log_steps,
        "message": msg_result
    }, ensure_ascii=False, indent=2)

def create_branch_readme(day_number: str, topic: str, learned_info: str, branch_name: str, code_link: str = "", video_link: str = "") -> str:
    """Генерирует и заносит локальный README.md строго для конкретной ветки."""
    day_key = str(day_number).strip()
    branch = branch_name.strip() or f"day{day_key}"

    state = _load_state()
    day_info = state.get("assignments", {}).get(day_key, {})

    final_code_link = code_link.strip() or day_info.get("code_link", f"https://github.com/user/ai_advent_1/blob/{branch}/day{day_key}.py")
    final_video_link = video_link.strip() or day_info.get("video_link", "ссылка на видео")

    readme_content = f"""# 🚀 AI Advent — День {day_key}: {topic}

> **Ветка репозитория:** `{branch}`
> **Дата обновления:** {time.strftime('%Y-%m-%d %H:%M')}

---

## 🛠 Проделанная работа
- Реализовано задание **{day_key}-го дня** в ветке `{branch}`.
- Точечное добавление файлов и настройка Git MCP Сервера.

---

## 💡 Новые знания и концепции, изученные за день
{learned_info.strip()}
"""

    readme_file = ROOT_DIR / "README.md"
    readme_file.write_text(readme_content, encoding="utf-8")

    # Точечно индексируем только README.md
    _run_git_cmd(["add", "README.md"])

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
        "message": f"✅ Файл README.md для ветки {branch} создан и проиндексирован!"
    }, ensure_ascii=False, indent=2)

def format_submission_comments(day_number: str, branch_name: str, code_link: str, video_link: str = "") -> str:
    """Формирует два точных комментария сдачи для Google Таблицы."""
    day_key = str(day_number).strip()
    branch = branch_name.strip() or f"day{day_key}"

    code_url = code_link.strip() or f"https://github.com/user/ai_advent_1/blob/{branch}/day{day_key}.py"
    video_url = video_link.strip() or "https://youtu.be/..."

    code_comment = f"код (ветка {branch}): {code_url}"
    video_comment = f"видео: {video_url}"

    state = _load_state()
    assignments = state.setdefault("assignments", {})
    day_info = assignments.setdefault(day_key, {})

    day_info["branch_name"] = branch
    day_info["code_link"] = code_url
    day_info["video_link"] = video_url
    day_info["code_comment"] = code_comment
    day_info["video_comment"] = video_comment
    day_info["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    day_info["status"] = "fully_submitted" if (video_url and "http" in video_url) else "code_submitted"
    _save_state(state)

    return json.dumps({
        "status": "success",
        "day": day_key,
        "branch": branch,
        "code_comment": code_comment,
        "video_comment": video_comment,
        "message": "✅ Сформированы 2 комментария для Google Таблицы с кнопками скопировать!"
    }, ensure_ascii=False, indent=2)

TOOLS = [
    {
        "name": "git_status_check",
        "description": "Проверяет активную Git-ветку и список нескоммиченных или измененных файлов.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "git_commit_and_push",
        "description": "Точечно индексирует только выбранные файлы (target_files), переключает ветку, делает коммит и пушит на GitHub.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "branch_name": {"type": "string", "description": "Имя ветки Git (например 'day17')"},
                "target_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Список конкретных файлов для коммита (например ['day17.py', 'mcp_server_git.py', 'README.md'])"
                },
                "commit_message": {"type": "string", "description": "Сообщение коммита (необязательно)"}
            },
            "required": ["branch_name", "target_files"]
        }
    },
    {
        "name": "create_branch_readme",
        "description": "Генерирует README.md для текущей ветки с описанием темы дня и изученного материала.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "day_number": {"type": "string", "description": "Номер дня курса (например '17')"},
                "topic": {"type": "string", "description": "Тема дня (например 'Первый инструмент MCP')"},
                "learned_info": {"type": "string", "description": "Описание новых изученных знаний и концепций"},
                "branch_name": {"type": "string", "description": "Имя текущей ветки"},
                "code_link": {"type": "string", "description": "Ссылка на код"},
                "video_link": {"type": "string", "description": "Ссылка на видео"}
            },
            "required": ["day_number", "topic", "learned_info", "branch_name"]
        }
    },
    {
        "name": "format_submission_comments",
        "description": "Формирует 2 точных комментария для Google Таблицы: 'код (ветка $branch): $link' и 'видео: $link'.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "day_number": {"type": "string", "description": "Номер дня курса (например '17')"},
                "branch_name": {"type": "string", "description": "Имя ветки Git"},
                "code_link": {"type": "string", "description": "Ссылка на код"},
                "video_link": {"type": "string", "description": "Ссылка на видео"}
            },
            "required": ["day_number", "branch_name", "code_link"]
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
                    "name": "git-assignment-server",
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
        if tool_name == "git_status_check":
            result_text = git_status_check()
        elif tool_name == "git_commit_and_push":
            result_text = git_commit_and_push(
                arguments.get("branch_name", "day17"),
                arguments.get("target_files", ["day17.py", "mcp_server_git.py", "README.md"]),
                arguments.get("commit_message", "")
            )
        elif tool_name == "create_branch_readme":
            result_text = create_branch_readme(
                arguments.get("day_number", "17"),
                arguments.get("topic", "Первый инструмент MCP"),
                arguments.get("learned_info", ""),
                arguments.get("branch_name", "day17"),
                arguments.get("code_link", ""),
                arguments.get("video_link", "")
            )
        elif tool_name == "format_submission_comments":
            result_text = format_submission_comments(
                arguments.get("day_number", "17"),
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
