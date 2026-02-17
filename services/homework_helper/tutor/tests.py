import json
import urllib.error
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase


class HelperChatAuthTests(TestCase):
    def setUp(self):
        cache.clear()

    def _post_chat(self, payload: dict):
        return self.client.post(
            "/helper/chat",
            data=json.dumps(payload),
            content_type="application/json",
        )

    def test_chat_requires_class_or_staff_session(self):
        resp = self._post_chat({"message": "help"})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json().get("error"), "unauthorized")

    @patch("tutor.views._ollama_chat", return_value=("Try this step first.", "fake-model"))
    @patch.dict("os.environ", {"HELPER_LLM_BACKEND": "ollama"}, clear=False)
    def test_chat_allows_student_session(self, _chat_mock):
        session = self.client.session
        session["student_id"] = 101
        session["class_id"] = 5
        session.save()

        resp = self._post_chat({"message": "How do I move a sprite?"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("text"), "Try this step first.")

    @patch("tutor.views.emit_helper_chat_access_event")
    @patch("tutor.views._ollama_chat", return_value=("Try this step first.", "fake-model"))
    @patch.dict("os.environ", {"HELPER_LLM_BACKEND": "ollama"}, clear=False)
    def test_chat_emits_helper_access_event_hook(self, _chat_mock, event_mock):
        session = self.client.session
        session["student_id"] = 101
        session["class_id"] = 5
        session.save()

        resp = self._post_chat({"message": "How do I move a sprite?"})
        self.assertEqual(resp.status_code, 200)
        event_mock.assert_called_once()

    @patch("tutor.views._ollama_chat", return_value=("Hint", "fake-model"))
    @patch.dict(
        "os.environ",
        {
            "HELPER_LLM_BACKEND": "ollama",
            "HELPER_RATE_LIMIT_PER_MINUTE": "1",
            "HELPER_RATE_LIMIT_PER_IP_PER_MINUTE": "10",
        },
        clear=False,
    )
    def test_chat_rate_limits_per_actor(self, _chat_mock):
        session = self.client.session
        session["student_id"] = 101
        session["class_id"] = 5
        session.save()

        first = self._post_chat({"message": "first"})
        second = self._post_chat({"message": "second"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertEqual(second.json().get("error"), "rate_limited")

    @patch("tutor.views.time.sleep", return_value=None)
    @patch.dict(
        "os.environ",
        {
            "HELPER_LLM_BACKEND": "ollama",
            "HELPER_BACKEND_MAX_ATTEMPTS": "2",
            "HELPER_BACKOFF_SECONDS": "0",
        },
        clear=False,
    )
    def test_chat_retries_backend_then_succeeds(self, _sleep_mock):
        session = self.client.session
        session["student_id"] = 101
        session["class_id"] = 5
        session.save()

        with patch(
            "tutor.views._ollama_chat",
            side_effect=[urllib.error.URLError("temp"), ("Recovered", "fake-model")],
        ) as chat_mock:
            resp = self._post_chat({"message": "retry please"})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("text"), "Recovered")
        self.assertEqual(resp.json().get("attempts"), 2)
        self.assertTrue(resp.json().get("request_id"))
        self.assertEqual(chat_mock.call_count, 2)

    @patch("tutor.views.time.sleep", return_value=None)
    @patch.dict(
        "os.environ",
        {
            "HELPER_LLM_BACKEND": "ollama",
            "HELPER_BACKEND_MAX_ATTEMPTS": "2",
            "HELPER_BACKOFF_SECONDS": "0",
        },
        clear=False,
    )
    def test_chat_returns_502_after_retry_exhausted(self, _sleep_mock):
        session = self.client.session
        session["student_id"] = 101
        session["class_id"] = 5
        session.save()

        with patch(
            "tutor.views._ollama_chat",
            side_effect=urllib.error.URLError("still down"),
        ) as chat_mock:
            resp = self._post_chat({"message": "retry fail"})

        self.assertEqual(resp.status_code, 502)
        self.assertIn(resp.json().get("error"), {"ollama_error", "backend_error"})
        self.assertEqual(chat_mock.call_count, 2)

    @patch.dict("os.environ", {"HELPER_LLM_BACKEND": "ollama"}, clear=False)
    def test_chat_returns_503_when_backend_circuit_open(self):
        session = self.client.session
        session["student_id"] = 101
        session["class_id"] = 5
        session.save()

        cache.set("helper:circuit_open:ollama", 1, timeout=30)
        with patch("tutor.views._ollama_chat") as chat_mock:
            resp = self._post_chat({"message": "hello"})

        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json().get("error"), "backend_unavailable")
        self.assertEqual(chat_mock.call_count, 0)
