#!/usr/bin/env python3
"""
MCP Client
Клиент для взаимодействия с MCP сервером по протоколу JSON-RPC через stdio.
"""

import sys
import os
import json
import subprocess
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional

class MCPClient:
    def __init__(self, server_script_path: str):
        self.server_script_path = str(Path(server_script_path).resolve())
        self.process: Optional[subprocess.Popen] = None
        self.msg_id = 1
        self._lock = threading.Lock()
        self.tools: List[Dict[str, Any]] = []
        self.server_info: Dict[str, Any] = {}
        self.is_connected = False
        self.start()

    def _send_request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        if not self.process or self.process.poll() is not None:
            return {"error": "MCP сервер не запущен"}

        with self._lock:
            req_id = self.msg_id
            self.msg_id += 1

            req = {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": method
            }
            if params is not None:
                req["params"] = params

            raw_req = json.dumps(req) + "\n"
            try:
                self.process.stdin.write(raw_req.encode("utf-8"))
                self.process.stdin.flush()

                raw_resp = self.process.stdout.readline().decode("utf-8")
                if not raw_resp:
                    return {"error": "Пустой ответ от MCP сервера"}
                return json.loads(raw_resp)
            except Exception as e:
                return {"error": f"Ошибка связи с MCP сервером: {e}"}

    def _send_notification(self, method: str, params: Optional[Dict[str, Any]] = None):
        if not self.process or self.process.poll() is not None:
            return
        with self._lock:
            req = {"jsonrpc": "2.0", "method": method}
            if params is not None:
                req["params"] = params
            raw_req = json.dumps(req) + "\n"
            try:
                self.process.stdin.write(raw_req.encode("utf-8"))
                self.process.stdin.flush()
            except Exception:
                pass

    def start(self):
        """Запускает процесс MCP сервера и инициализирует сессию."""
        try:
            self.process = subprocess.Popen(
                [sys.executable, self.server_script_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0
            )

            # 1. Initialize
            init_resp = self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "ai-advent-client", "version": "1.0.0"}
            })

            if init_resp and "result" in init_resp:
                self.server_info = init_resp["result"].get("serverInfo", {})
                self._send_notification("notifications/initialized")
                self.is_connected = True
                self.refresh_tools()
            else:
                self.is_connected = False
        except Exception as e:
            print(f"[MCPClient] Error starting server: {e}")
            self.is_connected = False

    def refresh_tools(self) -> List[Dict[str, Any]]:
        """Запрашивает актуальный список инструментов MCP сервера."""
        if not self.is_connected:
            return []
        resp = self._send_request("tools/list")
        if resp and "result" in resp and "tools" in resp["result"]:
            self.tools = resp["result"]["tools"]
        return self.tools

    def call_tool(self, tool_name: str, arguments: Dict[str, Any] = None) -> str:
        """Вызывает инструмент MCP сервера и возвращает результат."""
        if not self.is_connected:
            return "Ошибка: MCP сервер не подключен."

        resp = self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments or {}
        })

        if not resp:
            return "Ошибка: нет ответа от MCP сервера."
        if "error" in resp:
            return f"Ошибка MCP: {resp['error']}"

        if "result" in resp and "content" in resp["result"]:
            contents = resp["result"]["content"]
            texts = [item.get("text", "") for item in contents if item.get("type") == "text"]
            return "\n".join(texts)

        return json.dumps(resp, ensure_ascii=False)

    def close(self):
        """Завершает процесс MCP сервера."""
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=2)
            self.is_connected = False
