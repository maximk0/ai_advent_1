"""Boundary checks for the local-only proxy without a model download or network."""

import io
import json
import unittest
import urllib.error
from unittest.mock import Mock, patch

import day26_web as web


class LocalModelTests(unittest.TestCase):
    def handler(self, method, path, body=b"", **headers):
        handler = Mock()
        handler.command = method
        handler.path = path
        handler.headers = {"Content-Length": str(len(body)), "Host": "127.0.0.1:8002", **headers}
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        return handler

    def test_other_routes_are_left_to_existing_chat(self):
        for method, path in [("GET", "/api/state"), ("POST", "/api/chat"), ("GET", "/")]:
            handler = self.handler(method, path)
            handler.rfile.read = Mock(side_effect=AssertionError("Must not consume chat body"))
            self.assertFalse(web.handle_local_model(handler))
            handler.send_response.assert_not_called()

    def test_page_works_without_model_and_contains_three_presets(self):
        handler = self.handler("GET", "/local-model")
        with patch.object(web, "request_json", side_effect=AssertionError("Must not call model")):
            self.assertTrue(web.handle_local_model(handler))
        handler.send_response.assert_called_once_with(200)
        page = handler.wfile.getvalue().decode()
        self.assertNotIn("__PRESETS__", page)
        self.assertIn(web.PROMPTS[2][1], page)
        self.assertNotIn("cdn.", page)

    def test_disconnected_server_has_safe_error(self):
        handler = self.handler("GET", "/api/local-model/status")
        with patch.object(web, "request_json", side_effect=OSError("private internal log")):
            web.handle_local_model(handler)
        handler.send_response.assert_called_once_with(503)
        response = json.loads(handler.wfile.getvalue())
        self.assertFalse(response["connected"])
        self.assertIn("Запустите llama.cpp", response["error"])
        self.assertNotIn("private", response["error"])

    def test_loading_timeout_and_invalid_upstream(self):
        for error, status in [
            (urllib.error.HTTPError("", 503, "loading", {}, None), 503),
            (TimeoutError(), 504),
            (ValueError("bad JSON"), 502),
        ]:
            with self.subTest(error=type(error).__name__), patch.object(web, "request_json", side_effect=error):
                with self.assertRaises(web.LocalModelError) as result:
                    web.selected_model()
                self.assertEqual(result.exception.status, status)

    def test_rejects_invalid_questions_before_calling_model(self):
        with patch.object(web, "request_json") as request:
            for prompt in ["", "  ", None, 123, "a" * 6001]:
                with self.subTest(prompt_type=type(prompt).__name__), self.assertRaises(web.LocalModelError) as result:
                    web.complete_chat({"message": prompt})
                self.assertEqual(result.exception.status, 400)
            request.assert_not_called()

    def test_uses_loaded_model_and_hides_reasoning(self):
        with patch.object(web, "selected_model", return_value="actual-model"), patch.object(web, "local_request", return_value={
            "choices": [{"message": {"content": "<think>private thoughts</think>84 куста"}, "finish_reason": "length"}]
        }) as request:
            result = web.complete_chat({"message": "  Сколько кустов?  "})
        self.assertEqual(result["answer"], "84 куста")
        self.assertTrue(result["truncated"])
        path, payload = request.call_args.args
        self.assertEqual(path, "/v1/chat/completions")
        self.assertEqual(payload["model"], "actual-model")
        self.assertEqual(payload["messages"][-1]["content"], "Сколько кустов?")
        self.assertFalse(payload["chat_template_kwargs"]["enable_thinking"])

    def test_missing_or_unfinished_answer_is_error(self):
        for response in [{}, {"choices": []}, {"choices": [{"message": {"content": None}}]}, {"choices": [{"message": {"content": "<think>unfinished"}}]}]:
            with patch.object(web, "selected_model", return_value="model"), patch.object(web, "local_request", return_value=response):
                with self.assertRaises(web.LocalModelError):
                    web.complete_chat({"message": "Вопрос"})

    def test_malformed_body_and_cross_origin_are_rejected(self):
        for body, headers, status in [(b"{", {}, 400), (b"[]", {}, 400), (b'{}', {"Origin": "https://other.example"}, 403)]:
            handler = self.handler("POST", "/api/local-model/chat", body, **headers)
            with patch.object(web, "request_json") as request:
                self.assertTrue(web.handle_local_model(handler))
                request.assert_not_called()
            handler.send_response.assert_called_once_with(status)


if __name__ == "__main__":
    unittest.main()
