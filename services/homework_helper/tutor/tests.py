import json
import urllib.error
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db.utils import ProgrammingError
from django.test import TestCase, override_settings
from common.helper_scope import issue_scope_token

from . import views


class HelperChatAuthTests(TestCase):
    def setUp(self):
        cache.clear()

    def _scope_token(self) -> str:
        return issue_scope_token(
            context="Lesson scope: Session 1",
            topics=["scratch motion"],
            allowed_topics=["scratch motion", "sprites"],
            reference="piper_scratch",
        )

    def _post_chat(self, payload: dict, *, include_scope: bool = True):
        body = dict(payload)
        if include_scope and "scope_token" not in body:
            body["scope_token"] = self._scope_token()
        return self.client.post(
            "/helper/chat",
            data=json.dumps(body),
            content_type="application/json",
        )

    def test_chat_requires_class_or_staff_session(self):
        resp = self._post_chat({"message": "help"})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json().get("error"), "unauthorized")

    def test_redact_masks_email_and_phone(self):
        raw = "Email me at student@example.org or call 612-555-0123 please."
        redacted = views._redact(raw)
        self.assertIn("[REDACTED_EMAIL]", redacted)
        self.assertIn("[REDACTED_PHONE]", redacted)
        self.assertNotIn("student@example.org", redacted)
        self.assertNotIn("612-555-0123", redacted)

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

    @patch("tutor.views._ollama_chat", return_value=("Try this step first.", "fake-model"))
    @patch.dict("os.environ", {"HELPER_LLM_BACKEND": "ollama"}, clear=False)
    def test_chat_redacts_message_before_backend_call(self, chat_mock):
        session = self.client.session
        session["student_id"] = 101
        session["class_id"] = 5
        session.save()

        resp = self._post_chat(
            {
                "message": (
                    "Need help with sprites. "
                    "Contact student@example.org or 612-555-0123."
                )
            }
        )
        self.assertEqual(resp.status_code, 200)
        backend_message = str(chat_mock.call_args[0][3])
        self.assertIn("[REDACTED_EMAIL]", backend_message)
        self.assertIn("[REDACTED_PHONE]", backend_message)
        self.assertNotIn("student@example.org", backend_message)
        self.assertNotIn("612-555-0123", backend_message)

    @patch("tutor.views._student_session_exists", return_value=False)
    def test_chat_rejects_stale_student_session(self, _exists_mock):
        session = self.client.session
        session["student_id"] = 101
        session["class_id"] = 5
        session.save()

        resp = self._post_chat({"message": "help"})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json().get("error"), "unauthorized")

    @patch("tutor.views._ollama_chat", return_value=("Hint", "fake-model"))
    @patch.dict("os.environ", {"HELPER_LLM_BACKEND": "ollama"}, clear=False)
    def test_chat_requires_scope_token_for_student_sessions(self, _chat_mock):
        session = self.client.session
        session["student_id"] = 101
        session["class_id"] = 5
        session.save()

        resp = self._post_chat({"message": "How do I move a sprite?"}, include_scope=False)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("error"), "missing_scope_token")

    @patch("tutor.views._ollama_chat", return_value=("Hint", "fake-model"))
    @patch.dict("os.environ", {"HELPER_LLM_BACKEND": "ollama"}, clear=False)
    def test_chat_rejects_invalid_scope_token(self, _chat_mock):
        session = self.client.session
        session["student_id"] = 101
        session["class_id"] = 5
        session.save()

        resp = self._post_chat({"message": "How do I move a sprite?", "scope_token": "not-real-token"})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("error"), "invalid_scope_token")

    @patch("tutor.views._ollama_chat", return_value=("Hint", "fake-model"))
    @patch("tutor.views.build_instructions", return_value="system instructions")
    @patch.dict("os.environ", {"HELPER_LLM_BACKEND": "ollama"}, clear=False)
    def test_scope_token_overrides_tampered_client_scope(self, build_instructions_mock, _chat_mock):
        session = self.client.session
        session["student_id"] = 101
        session["class_id"] = 5
        session.save()

        token = issue_scope_token(
            context="Signed context",
            topics=["signed topic"],
            allowed_topics=["signed allowed"],
            reference="signed_reference",
        )
        resp = self._post_chat(
            {
                "message": "Help",
                "scope_token": token,
                "context": "tampered context",
                "topics": ["tampered topic"],
                "allowed_topics": ["tampered allowed"],
                "reference": "tampered_reference",
            }
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("scope_verified"))
        build_kwargs = build_instructions_mock.call_args.kwargs
        self.assertEqual(build_kwargs["context"], "Signed context")
        self.assertEqual(build_kwargs["topics"], ["signed topic"])
        self.assertEqual(build_kwargs["allowed_topics"], ["signed allowed"])
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

    def test_student_session_exists_fails_open_when_classhub_table_unavailable(self):
        with patch("tutor.views.connection.cursor", side_effect=ProgrammingError("missing table")):
            self.assertTrue(views._student_session_exists(student_id=1, class_id=2))
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

    @patch("tutor.views._ollama_chat", return_value=("A" * 300, "fake-model"))
    @patch.dict(
        "os.environ",
        {
            "HELPER_LLM_BACKEND": "ollama",
            "HELPER_RESPONSE_MAX_CHARS": "220",
        },
        clear=False,
    )
    def test_chat_truncates_response_text(self, _chat_mock):
        session = self.client.session
        session["student_id"] = 101
        session["class_id"] = 5
        session.save()

        resp = self._post_chat({"message": "truncate"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("truncated"))
        self.assertEqual(len(resp.json().get("text") or ""), 220)


class HelperAdminAccessTests(TestCase):
    def test_helper_admin_requires_superuser(self):
        user = get_user_model().objects.create_user(
            username="teacher",
            password="pw12345",
            is_staff=True,
            is_superuser=False,
        )
        self.client.force_login(user)

        resp = self.client.get("/admin/", follow=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])

    def test_helper_admin_requires_2fa_for_superuser(self):
        user = get_user_model().objects.create_superuser(
            username="admin",
            password="pw12345",
            email="admin@example.org",
        )
        self.client.force_login(user)

        resp = self.client.get("/admin/", follow=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])

    @override_settings(ADMIN_2FA_REQUIRED=False)
    def test_helper_admin_allows_superuser_when_2fa_disabled(self):
        user = get_user_model().objects.create_superuser(
            username="admin2",
            password="pw12345",
            email="admin2@example.org",
        )
        self.client.force_login(user)

        resp = self.client.get("/admin/")
        self.assertEqual(resp.status_code, 200)
