import json
import tempfile
import urllib.error
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db.utils import ProgrammingError
from django.test import TestCase, override_settings
from common.helper_scope import issue_scope_token

from . import classhub_events
from . import views


class HelperChatAuthTests(TestCase):
    def setUp(self):
        cache.clear()
        self._topic_filter_patch = patch.dict("os.environ", {"HELPER_TOPIC_FILTER_MODE": "soft"}, clear=False)
        self._topic_filter_patch.start()
        self.addCleanup(self._topic_filter_patch.stop)

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

    @patch.dict(
        "os.environ",
        {
            "HELPER_LLM_BACKEND": "mock",
            "HELPER_MOCK_RESPONSE_TEXT": "Mock hint: start with one sprite and one motion block.",
        },
        clear=False,
    )
    def test_chat_supports_mock_backend(self):
        session = self.client.session
        session["student_id"] = 101
        session["class_id"] = 5
        session.save()

        resp = self._post_chat({"message": "How do I move a sprite?"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("text"), "Mock hint: start with one sprite and one motion block.")
        self.assertEqual(resp.json().get("model"), "mock-tutor-v1")

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

    @patch("tutor.views._ollama_chat", return_value=("backend should not be called", "fake-model"))
    @patch.dict("os.environ", {"HELPER_LLM_BACKEND": "ollama"}, clear=False)
    def test_chat_uses_deterministic_piper_hardware_triage(self, chat_mock):
        session = self.client.session
        session["student_id"] = 101
        session["class_id"] = 5
        session.save()

        resp = self._post_chat(
            {
                "message": "In StoryMode, my jump button in Cheeseteroid is not working after moving jumper wires.",
            }
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body.get("triage_mode"), "piper_hardware")
        self.assertEqual(body.get("attempts"), 0)
        text = (body.get("text") or "").lower()
        self.assertIn("which storymode mission + step", text)
        self.assertIn("do this one check now", text)
        self.assertIn("retest only that same input", text)
        self.assertEqual(chat_mock.call_count, 0)

    @patch("tutor.views._ollama_chat", return_value=("Hint", "fake-model"))
    @patch.dict(
        "os.environ",
        {
            "HELPER_LLM_BACKEND": "ollama",
            "HELPER_PIPER_HARDWARE_TRIAGE_ENABLED": "0",
        },
        clear=False,
    )
    def test_chat_can_disable_piper_hardware_triage(self, chat_mock):
        session = self.client.session
        session["student_id"] = 101
        session["class_id"] = 5
        session.save()

        resp = self._post_chat(
            {
                "message": "My StoryMode breadboard buttons are not responding.",
            }
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("text"), "Hint")
        self.assertIsNone(resp.json().get("triage_mode"))
        self.assertEqual(chat_mock.call_count, 1)

    @patch("tutor.views._ollama_chat", return_value=("Hint", "fake-model"))
    @patch.dict("os.environ", {"HELPER_LLM_BACKEND": "ollama"}, clear=False)
    def test_chat_does_not_apply_piper_hardware_triage_outside_piper_context(self, chat_mock):
        session = self.client.session
        session["student_id"] = 101
        session["class_id"] = 5
        session.save()

        token = issue_scope_token(
            context="Lesson scope: fractions",
            topics=["fractions"],
            allowed_topics=["fractions"],
            reference="fractions_reference",
        )
        resp = self._post_chat(
            {
                "message": "My breadboard button is not working.",
                "scope_token": token,
            }
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json().get("text"), "Hint")
        self.assertIsNone(resp.json().get("triage_mode"))
        self.assertEqual(chat_mock.call_count, 1)

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

    @patch("tutor.views._ollama_chat", return_value=("Grounded hint", "fake-model"))
    @patch("tutor.views.build_instructions", return_value="system instructions")
    @patch.dict("os.environ", {"HELPER_LLM_BACKEND": "ollama"}, clear=False)
    def test_chat_includes_reference_citations_in_prompt_and_response(self, build_instructions_mock, _chat_mock):
        session = self.client.session
        session["student_id"] = 101
        session["class_id"] = 5
        session.save()

        with tempfile.TemporaryDirectory() as temp_dir:
            ref_path = Path(temp_dir) / "piper_scratch.md"
            ref_path.write_text(
                "\n".join(
                    [
                        "# Session 1",
                        "Check jumper seating before changing code.",
                        "",
                        "Use one-wire changes, then retest the same control.",
                        "",
                        "Shared ground must stay connected for controls to respond.",
                    ]
                ),
                encoding="utf-8",
            )
            with patch.dict(
                "os.environ",
                {"HELPER_REFERENCE_DIR": temp_dir},
                clear=False,
            ):
                resp = self._post_chat({"message": "My jump button does not respond in StoryMode."})

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        citations = body.get("citations") or []
        self.assertTrue(citations)
        self.assertEqual(citations[0].get("id"), "L1")
        self.assertEqual(citations[0].get("source"), "piper_scratch")
        self.assertTrue(citations[0].get("text"))

        build_kwargs = build_instructions_mock.call_args.kwargs
        self.assertIn("Lesson excerpts:", build_kwargs.get("reference_citations", ""))

    @patch("tutor.views._ollama_chat", return_value=("Hint", "fake-model"))
    @patch("tutor.views.build_instructions", return_value="system instructions")
    @patch.dict("os.environ", {"HELPER_LLM_BACKEND": "ollama"}, clear=False)
    def test_staff_unsigned_scope_fields_are_ignored(self, build_instructions_mock, _chat_mock):
        staff = get_user_model().objects.create_user(
            username="teacher1",
            password="pw12345",
            is_staff=True,
        )
        self.client.force_login(staff)

        resp = self._post_chat(
            {
                "message": "Help",
                "context": "tampered context",
                "topics": ["tampered topic"],
                "allowed_topics": ["tampered allowed"],
                "reference": "tampered_reference",
            },
            include_scope=False,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json().get("scope_verified"))
        build_kwargs = build_instructions_mock.call_args.kwargs
        self.assertEqual(build_kwargs["context"], "")
        self.assertEqual(build_kwargs["topics"], [])
        self.assertEqual(build_kwargs["allowed_topics"], [])


    @override_settings(HELPER_REQUIRE_SCOPE_TOKEN_FOR_STAFF=True)
    @patch("tutor.views._ollama_chat", return_value=("Hint", "fake-model"))
    @patch.dict("os.environ", {"HELPER_LLM_BACKEND": "ollama"}, clear=False)
    def test_staff_can_be_forced_to_require_scope_token(self, _chat_mock):
        staff = get_user_model().objects.create_user(
            username="teacher2",
            password="pw12345",
            is_staff=True,
        )
        self.client.force_login(staff)

        resp = self._post_chat({"message": "Help"}, include_scope=False)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("error"), "missing_scope_token")

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

    @override_settings(HELPER_REQUIRE_CLASSHUB_TABLE=True)
    def test_student_session_exists_fails_closed_when_classhub_table_required(self):
        with patch("tutor.views.connection.cursor", side_effect=ProgrammingError("missing table")):
            self.assertFalse(views._student_session_exists(student_id=1, class_id=2))
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


class ClassHubEventForwardingTests(TestCase):
    @override_settings(
        CLASSHUB_INTERNAL_EVENTS_URL="http://classhub_web:8000/internal/events/helper-chat-access",
        CLASSHUB_INTERNAL_EVENTS_TOKEN="token-123",
        CLASSHUB_INTERNAL_EVENTS_TIMEOUT_SECONDS=3,
    )
    def test_emit_helper_chat_access_event_posts_to_internal_endpoint(self):
        with patch("tutor.classhub_events.urllib.request.urlopen") as urlopen_mock:
            response = SimpleNamespace(status=200)
            urlopen_mock.return_value.__enter__.return_value = response
            classhub_events.emit_helper_chat_access_event(
                classroom_id=5,
                student_id=101,
                ip_address="127.0.0.1",
                details={"request_id": "req-1"},
            )

        req = urlopen_mock.call_args.args[0]
        self.assertEqual(req.full_url, "http://classhub_web:8000/internal/events/helper-chat-access")
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.headers.get("Content-type"), "application/json")
        self.assertEqual(req.headers.get("X-classhub-internal-token"), "token-123")
        self.assertEqual(urlopen_mock.call_args.kwargs.get("timeout"), 3)

    @override_settings(
        CLASSHUB_INTERNAL_EVENTS_URL="",
        CLASSHUB_INTERNAL_EVENTS_TOKEN="",
    )
    def test_emit_helper_chat_access_event_skips_when_config_missing(self):
        with patch("tutor.classhub_events.urllib.request.urlopen") as urlopen_mock:
            classhub_events.emit_helper_chat_access_event(
                classroom_id=5,
                student_id=101,
                ip_address="127.0.0.1",
                details={"request_id": "req-1"},
            )
        self.assertFalse(urlopen_mock.called)

    @override_settings(
        CLASSHUB_INTERNAL_EVENTS_URL="http://classhub_web:8000/internal/events/helper-chat-access",
        CLASSHUB_INTERNAL_EVENTS_TOKEN="token-123",
    )
    def test_emit_helper_chat_access_event_swallows_http_errors(self):
        with patch(
            "tutor.classhub_events.urllib.request.urlopen",
            side_effect=urllib.error.HTTPError(
                url="http://classhub_web:8000/internal/events/helper-chat-access",
                code=403,
                msg="forbidden",
                hdrs=None,
                fp=None,
            ),
        ) as urlopen_mock:
            classhub_events.emit_helper_chat_access_event(
                classroom_id=5,
                student_id=101,
                ip_address="127.0.0.1",
                details={"request_id": "req-1"},
            )
        self.assertTrue(urlopen_mock.called)


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


class HelperSecurityHeaderTests(TestCase):
    @override_settings(CSP_REPORT_ONLY_POLICY="default-src 'self'")
    def test_healthz_sets_csp_report_only_header_when_configured(self):
        resp = self.client.get("/helper/healthz")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Security-Policy-Report-Only"], "default-src 'self'")
