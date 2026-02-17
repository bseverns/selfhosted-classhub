import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db.utils import ProgrammingError
from django.test import TestCase

from . import views


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

    @patch("tutor.views._student_session_exists", return_value=False)
    def test_chat_rejects_stale_student_session(self, _exists_mock):
        session = self.client.session
        session["student_id"] = 101
        session["class_id"] = 5
        session.save()

        resp = self._post_chat({"message": "help"})
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json().get("error"), "unauthorized")

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

    def test_helper_admin_allows_superuser(self):
        user = get_user_model().objects.create_superuser(
            username="admin",
            password="pw12345",
            email="admin@example.org",
        )
        self.client.force_login(user)

        resp = self.client.get("/admin/")
        self.assertEqual(resp.status_code, 200)
