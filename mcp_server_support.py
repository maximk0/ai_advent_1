#!/usr/bin/env python3
"""Read-only MCP server exposing demo support users and tickets from JSON."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "support_data" / "users_tickets.json"

TOOLS = [
    {
        "name": "list_support_tickets",
        "description": "Возвращает список демонстрационных тикетов поддержки без секретов.",
        "inputSchema": {
            "type": "object",
            "properties": {"status": {"type": "string", "description": "Необязательный фильтр по статусу."}},
        },
    },
    {
        "name": "get_support_ticket",
        "description": "Возвращает тикет, карточки пользователя и компании клиента по точному ID.",
        "inputSchema": {
            "type": "object",
            "properties": {"ticket_id": {"type": "string", "description": "Например SUP-2041."}},
            "required": ["ticket_id"],
        },
    },
]


def _load_data() -> dict:
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Файл с демонстрационными обращениями должен содержать JSON-объект.")
    return data


def list_support_tickets(status: str = "") -> str:
    data = _load_data()
    users = {user.get("user_id"): user for user in data.get("users", []) if isinstance(user, dict)}
    companies = {company.get("company_id"): company for company in data.get("companies", []) if isinstance(company, dict)}
    tickets = []
    for ticket in data.get("tickets", []):
        if not isinstance(ticket, dict):
            continue
        if status and str(ticket.get("status", "")).casefold() != status.casefold():
            continue
        user = users.get(ticket.get("user_id"), {})
        company = companies.get(ticket.get("company_id"), {})
        tickets.append({
            "ticket_id": ticket.get("ticket_id"),
            "status": ticket.get("status"),
            "subject": ticket.get("subject"),
            "question": ticket.get("question"),
            "user_name": user.get("display_name", "Неизвестный пользователь"),
            "user_role": user.get("role", ""),
            "company_name": company.get("name", "Неизвестная компания"),
            "plan": company.get("plan", ""),
            "seats_used": company.get("seats_used", ""),
            "seats_limit": company.get("seats_limit", ""),
        })
    return json.dumps(tickets, ensure_ascii=False)


def get_support_ticket(ticket_id: str) -> str:
    data = _load_data()
    ticket = next(
        (item for item in data.get("tickets", []) if isinstance(item, dict) and item.get("ticket_id") == ticket_id),
        None,
    )
    if ticket is None:
        return json.dumps({"error": "Тикет не найден."}, ensure_ascii=False)
    user = next(
        (item for item in data.get("users", []) if isinstance(item, dict) and item.get("user_id") == ticket.get("user_id")),
        {},
    )
    company = next(
        (item for item in data.get("companies", []) if isinstance(item, dict) and item.get("company_id") == ticket.get("company_id")),
        {},
    )
    return json.dumps({"ticket": ticket, "user": user, "company": company, "product": data.get("product", {})}, ensure_ascii=False)


def handle_json_rpc(raw: str) -> None:
    try:
        request = json.loads(raw)
    except json.JSONDecodeError:
        return
    request_id = request.get("id")
    method = request.get("method")

    if method == "notifications/initialized":
        return
    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "ai-advent-support-json", "version": "1.0.0"},
        }
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = request.get("params", {})
        name = params.get("name")
        arguments = params.get("arguments", {})
        if name == "list_support_tickets":
            content = list_support_tickets(str(arguments.get("status", "")))
        elif name == "get_support_ticket":
            content = get_support_ticket(str(arguments.get("ticket_id", "")))
        else:
            content = json.dumps({"error": f"Неизвестный инструмент: {name}"}, ensure_ascii=False)
        result = {"content": [{"type": "text", "text": content}]}
    else:
        return

    response = {"jsonrpc": "2.0", "id": request_id, "result": result}
    sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> None:
    for line in sys.stdin:
        if line.strip():
            handle_json_rpc(line)


if __name__ == "__main__":
    main()
