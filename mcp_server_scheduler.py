#!/usr/bin/env python3
"""
MCP Server: Scheduler & Background Tasks Manager (24/7)
Предоставляет инструменты для планирования отложенных напоминаний,
периодического сбора метрик в фоновом потоке, сохранения истории в scheduler_db.json
и генерации 24/7 суточной агрегированной сводки (Summary).
Работает по протоколу MCP JSON-RPC 2.0 через stdio.
"""

from __future__ import annotations

import sys
import os
import json
import time
import threading
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional

ROOT_DIR = Path(__file__).resolve().parent
DB_FILE = ROOT_DIR / "scheduler_db.json"
_DB_LOCK = threading.Lock()

def _load_db() -> Dict[str, Any]:
    if DB_FILE.exists():
        try:
            return json.loads(DB_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "reminders": [],
        "periodic_jobs": [],
        "collected_metrics": [],
        "logs": []
    }

def _save_db(data: Dict[str, Any]):
    try:
        DB_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        sys.stderr.write(f"Error saving scheduler db: {e}\n")

def _run_git_status() -> Dict[str, Any]:
    try:
        res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(ROOT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5
        )
        b_res = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(ROOT_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5
        )
        modified = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        branch = b_res.stdout.strip() or "main"
        return {"branch": branch, "modified_files_count": len(modified), "status": "clean" if not modified else "modified"}
    except Exception:
        return {"branch": "unknown", "modified_files_count": 0, "status": "ok"}

def _bg_scheduler_loop():
    """Фоновый поток планировщика 24/7."""
    while True:
        try:
            time.sleep(2)
            now_dt = datetime.now()
            now_str = now_dt.strftime("%Y-%m-%d %H:%M:%S")

            with _DB_LOCK:
                db = _load_db()
                changed = False

                # 1. Проверяем сработавшие напоминания
                for rem in db.get("reminders", []):
                    if not rem.get("triggered", False):
                        target_str = rem.get("target_time", "")
                        try:
                            target_dt = datetime.strptime(target_str, "%Y-%m-%d %H:%M:%S")
                            if now_dt >= target_dt:
                                rem["triggered"] = True
                                rem["triggered_at"] = now_str
                                log_msg = f"{now_str} [⏰ НАПОМИНАНИЕ СРАБОТАЛО]: {rem.get('text')}"
                                db.setdefault("logs", []).append(log_msg)
                                changed = True
                        except Exception:
                            pass

                # 2. Выполняем фоновые периодические задачи
                for job in db.get("periodic_jobs", []):
                    interval = int(job.get("interval_seconds", 30))
                    last_run_str = job.get("last_run", "")
                    should_run = False

                    if not last_run_str:
                        should_run = True
                    else:
                        try:
                            last_run_dt = datetime.strptime(last_run_str, "%Y-%m-%d %H:%M:%S")
                            if (now_dt - last_run_dt).total_seconds() >= interval:
                                should_run = True
                        except Exception:
                            should_run = True

                    if should_run:
                        job["last_run"] = now_str
                        job["run_count"] = job.get("run_count", 0) + 1

                        # Сбор фоновой метрики
                        git_info = _run_git_status()
                        metric_entry = {
                            "timestamp": now_str,
                            "job_name": job.get("name", "Фоновый сбор"),
                            "metric_type": job.get("metric_type", "system_stats"),
                            "data": git_info
                        }
                        db.setdefault("collected_metrics", []).append(metric_entry)
                        # Храним последние 50 метрик
                        if len(db["collected_metrics"]) > 50:
                            db["collected_metrics"] = db["collected_metrics"][-50:]

                        log_msg = f"{now_str} [🔄 ФОНОВАЯ ЗАДАЧА]: '{job.get('name')}' выполнена (запуск №{job['run_count']}). Статус Git: {git_info.get('status')} ({git_info.get('modified_files_count')} изм.)"
                        db.setdefault("logs", []).append(log_msg)
                        if len(db["logs"]) > 100:
                            db["logs"] = db["logs"][-100:]

                        changed = True

                if changed:
                    _save_db(db)

        except Exception as e:
            sys.stderr.write(f"Error in background scheduler loop: {e}\n")

# Запускаем фоновый демон планировщика при импорте модуля
_bg_thread = threading.Thread(target=_bg_scheduler_loop, daemon=True)
_bg_thread.start()

def add_reminder(text: str, delay_seconds: int = 30) -> str:
    """Планирует отложенное напоминание через N секунд."""
    rem_text = text.strip() or "Напоминание по умолчанию"
    delay = max(5, int(delay_seconds))

    now_dt = datetime.now()
    target_dt = now_dt + timedelta(seconds=delay)
    target_str = target_dt.strftime("%Y-%m-%d %H:%M:%S")

    rem_id = f"rem_{int(time.time())}"
    new_reminder = {
        "id": rem_id,
        "text": rem_text,
        "target_time": target_str,
        "created_at": now_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "triggered": False
    }

    with _DB_LOCK:
        db = _load_db()
        db.setdefault("reminders", []).append(new_reminder)
        db.setdefault("logs", []).append(f"{now_dt.strftime('%Y-%m-%d %H:%M:%S')} [➕ СОЗДАНО НАПОМИНАНИЕ]: '{rem_text}' на {target_str}")
        _save_db(db)

    return json.dumps({
        "status": "success",
        "reminder_id": rem_id,
        "text": rem_text,
        "target_time": target_str,
        "delay_seconds": delay,
        "message": f"⏰ Напоминание '{rem_text}' запланировано на {target_str} (через {delay} сек.)"
    }, ensure_ascii=False, indent=2)

def add_periodic_job(job_name: str, interval_seconds: int = 30, metric_type: str = "system_stats") -> str:
    """Регистрирует регулярную фоновую задачу сбора метрик каждые N секунд."""
    name = job_name.strip() or "Периодический мониторинг"
    interval = max(5, int(interval_seconds))

    job_id = f"job_{int(time.time())}"
    new_job = {
        "id": job_id,
        "name": name,
        "metric_type": metric_type.strip(),
        "interval_seconds": interval,
        "last_run": "",
        "run_count": 0
    }

    with _DB_LOCK:
        db = _load_db()
        db.setdefault("periodic_jobs", []).append(new_job)
        db.setdefault("logs", []).append(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [➕ ДОБАВЛЕНА ФОНОВАЯ ЗАДАЧА]: '{name}' (интервал: {interval} сек.)")
        _save_state = _save_db(db)

    return json.dumps({
        "status": "success",
        "job_id": job_id,
        "name": name,
        "interval_seconds": interval,
        "message": f"🔄 Фоновая задача '{name}' активирована и будет выполняться каждые {interval} сек. 24/7!"
    }, ensure_ascii=False, indent=2)

def list_active_jobs() -> str:
    """Возвращает список всех активных фоновых задач, напоминаний и их статусы."""
    with _DB_LOCK:
        db = _load_db()

    reminders = db.get("reminders", [])
    jobs = db.get("periodic_jobs", [])
    logs = db.get("logs", [])[-10:]

    return json.dumps({
        "total_reminders": len(reminders),
        "pending_reminders": [r for r in reminders if not r.get("triggered")],
        "triggered_reminders": [r for r in reminders if r.get("triggered")],
        "total_periodic_jobs": len(jobs),
        "periodic_jobs": jobs,
        "recent_logs": logs
    }, ensure_ascii=False, indent=2)

def get_aggregated_summary() -> str:
    """Формирует 24/7 суточную агрегированную сводку собранных метрик и выполненных задач."""
    with _DB_LOCK:
        db = _load_db()

    reminders = db.get("reminders", [])
    jobs = db.get("periodic_jobs", [])
    metrics = db.get("collected_metrics", [])
    logs = db.get("logs", [])

    triggered_count = len([r for r in reminders if r.get("triggered")])
    pending_count = len([r for r in reminders if not r.get("triggered")])

    summary_text = f"""📊 === 24/7 АГРЕГИРОВАННАЯ СВОДКА ПЛАНИРОВЩИКА (SUMMARY) ===
🕒 Время формирования: {time.strftime('%Y-%m-%d %H:%M:%S')}

⏰ НАПОМИНАНИЯ:
- Всего создано: {len(reminders)}
- Сработало: {triggered_count}
- В ожидании: {pending_count}

🔄 ФОНОВЫЕ ПЕРИОДИЧЕСКИЕ ЗАДАЧИ:
- Активных задач: {len(jobs)}
- Всего собрано замеров метрик: {len(metrics)}

📈 ПОСЛЕДНИЕ СОБРАННЫЕ МЕТРИКИ (TOP 3):
"""
    for m in metrics[-3:]:
        summary_text += f"- [{m.get('timestamp')}] {m.get('job_name')}: Ветка '{m.get('data', {}).get('branch')}', Изменений: {m.get('data', {}).get('modified_files_count')}\n"

    summary_text += f"\n📝 ПОСЛЕДНИЕ СОБЫТИЯ В ЛОГЕ (TOP 5):\n"
    for l in logs[-5:]:
        summary_text += f"- {l}\n"

    return json.dumps({
        "status": "success",
        "summary_formatted": summary_text,
        "metrics_count": len(metrics),
        "triggered_reminders_count": triggered_count,
        "pending_reminders_count": pending_count,
        "active_jobs_count": len(jobs)
    }, ensure_ascii=False, indent=2)

def trigger_job_now(job_name: str) -> str:
    """Принудительно выполняет фоновый сбор данных прямо сейчас."""
    target_name = job_name.strip()
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")

    git_info = _run_git_status()
    metric_entry = {
        "timestamp": now_str,
        "job_name": target_name or "Ручной запуск сбора",
        "metric_type": "manual_trigger",
        "data": git_info
    }

    with _DB_LOCK:
        db = _load_db()
        db.setdefault("collected_metrics", []).append(metric_entry)
        db.setdefault("logs", []).append(f"{now_str} [⚡ РУЧНОЙ ЗАПУСК]: Запущена задача '{target_name}'. Метрика сохранена.")
        _save_db(db)

    return json.dumps({
        "status": "success",
        "job_name": target_name,
        "timestamp": now_str,
        "data": git_info,
        "message": f"⚡ Задача '{target_name}' принудительно выполнена. Метрики сохранены в БД!"
    }, ensure_ascii=False, indent=2)

TOOLS = [
    {
        "name": "add_reminder",
        "description": "Запланировать отложенное напоминание с текстом через N секунд (например, через 30 секунд).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Текст напоминания"},
                "delay_seconds": {"type": "integer", "description": "Задержка в секундах (по умолчанию 30)"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "add_periodic_job",
        "description": "Запустить фоновый регулярный сбор данных каждые N секунд (например, каждые 20 секунд).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_name": {"type": "string", "description": "Название фоновой задачи"},
                "interval_seconds": {"type": "integer", "description": "Интервал сбора в секундах (по умолчанию 30)"},
                "metric_type": {"type": "string", "description": "Тип метрики (например 'system_stats')"}
            },
            "required": ["job_name"]
        }
    },
    {
        "name": "list_active_jobs",
        "description": "Показать все активные фоновые задачи, запланированные напоминания и логи.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_aggregated_summary",
        "description": "Получить 24/7 суточную агрегированную сводку (Summary) по всем фоновым метрикам и напоминаниям.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "trigger_job_now",
        "description": "Принудительно запустить фоновый сбор данных или задачу прямо сейчас.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_name": {"type": "string", "description": "Имя задачи для запуска"}
            },
            "required": ["job_name"]
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
                    "name": "scheduler-247-server",
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
        if tool_name == "add_reminder":
            result_text = add_reminder(
                arguments.get("text", "Напоминание"),
                int(arguments.get("delay_seconds", 30))
            )
        elif tool_name == "add_periodic_job":
            result_text = add_periodic_job(
                arguments.get("job_name", "Мониторинг"),
                int(arguments.get("interval_seconds", 30)),
                arguments.get("metric_type", "system_stats")
            )
        elif tool_name == "list_active_jobs":
            result_text = list_active_jobs()
        elif tool_name == "get_aggregated_summary":
            result_text = get_aggregated_summary()
        elif tool_name == "trigger_job_now":
            result_text = trigger_job_now(
                arguments.get("job_name", "Ручной запуск")
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
