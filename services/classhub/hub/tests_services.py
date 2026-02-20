import zipfile
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from common.request_safety import fixed_window_allow, token_bucket_allow

from .middleware import StudentSessionMiddleware
from .models import Class, StudentIdentity
from .services.markdown_content import (
    render_markdown_to_safe_html,
    split_lesson_markdown_for_audiences,
)
from .services.content_links import (
    build_asset_url,
    normalize_lesson_videos,
    parse_course_lesson_url,
    safe_filename,
)
from .services.release_state import (
    lesson_available_on,
    lesson_release_state,
    parse_release_date,
)
from .services.upload_policy import (
    front_matter_submission,
    parse_extensions,
)
from .services.upload_scan import scan_uploaded_file
from .services.upload_validation import validate_upload_content


def _sample_sb3_upload() -> SimpleUploadedFile:
    buf = BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("project.json", '{"targets":[],"meta":{"semver":"3.0.0"}}')
    return SimpleUploadedFile("project.sb3", buf.getvalue())


class UploadPolicyServiceTests(SimpleTestCase):
    def test_parse_extensions_normalizes_unique_list(self):
        self.assertEqual(parse_extensions("sb3, .PNG, .sb3"), [".sb3", ".png"])

    def test_front_matter_submission_parses_pipe_or_csv(self):
        row = front_matter_submission(
            {
                "submission": {
                    "type": "file",
                    "accepted": "sb3|png",
                    "naming": "studentname_session",
                }
            }
        )
        self.assertEqual(row["type"], "file")
        self.assertEqual(row["accepted_exts"], [".sb3", ".png"])
        self.assertEqual(row["naming"], "studentname_session")


class _FailingCache:
    def get(self, key):
        raise RuntimeError("cache down")

    def set(self, key, value, timeout=None):
        raise RuntimeError("cache down")

    def incr(self, key):
        raise RuntimeError("cache down")


class RequestSafetyRateLimitResilienceTests(SimpleTestCase):
    def test_fixed_window_allow_fails_open_when_cache_backend_errors(self):
        allowed = fixed_window_allow(
            "rl:test:key",
            limit=1,
            window_seconds=60,
            cache_backend=_FailingCache(),
            request_id="req-cache-down",
        )
        self.assertTrue(allowed)

    def test_token_bucket_allow_fails_open_when_cache_backend_errors(self):
        allowed = token_bucket_allow(
            "tb:test:key",
            capacity=10,
            refill_per_second=1.0,
            cache_backend=_FailingCache(),
            request_id="req-cache-down",
        )
        self.assertTrue(allowed)


class ReleaseStateServiceTests(SimpleTestCase):
    def test_parse_release_date_handles_invalid(self):
        self.assertIsNone(parse_release_date("not-a-date"))
        self.assertIsNotNone(parse_release_date("2026-02-17"))

    def test_lesson_available_on_prefers_front_matter(self):
        available = lesson_available_on(
            {"available_on": "2026-02-20"},
            {"available_on": "2026-03-01"},
        )
        self.assertEqual(str(available), "2026-02-20")

    def test_lesson_release_state_defaults_open_without_dates(self):
        request = SimpleNamespace(user=SimpleNamespace(is_authenticated=False, is_staff=False))
        state = lesson_release_state(request, {}, {}, classroom_id=0)
        self.assertFalse(state["is_locked"])
        self.assertIsNone(state["available_on"])


class MarkdownContentServiceTests(SimpleTestCase):
    def test_split_lesson_markdown_for_audiences(self):
        learner, teacher = split_lesson_markdown_for_audiences(
            "## Intro\nLearner content\n\n## Teacher prep\nTeacher notes"
        )
        self.assertIn("Learner content", learner)
        self.assertIn("Teacher notes", teacher)

    def test_render_markdown_to_safe_html_strips_script(self):
        html = render_markdown_to_safe_html("Hi<script>alert(1)</script>")
        self.assertIn("Hi", html)
        self.assertNotIn("<script", html)

    def test_render_markdown_to_safe_html_keeps_heading_anchor_ids(self):
        html = render_markdown_to_safe_html("# Intro Heading")
        self.assertIn('id="intro-heading"', html)

    def test_render_markdown_to_safe_html_blocks_images_by_default(self):
        html = render_markdown_to_safe_html('![diagram](https://cdn.example.org/d.png)')
        self.assertNotIn("<img", html)

    @override_settings(
        CLASSHUB_MARKDOWN_ALLOW_IMAGES=True,
        CLASSHUB_MARKDOWN_ALLOWED_IMAGE_HOSTS=["cdn.example.org"],
    )
    def test_render_markdown_allows_images_for_allowed_host(self):
        html = render_markdown_to_safe_html('![diagram](https://cdn.example.org/d.png)')
        self.assertIn("<img", html)
        self.assertIn('src="https://cdn.example.org/d.png"', html)

    @override_settings(
        CLASSHUB_MARKDOWN_ALLOW_IMAGES=True,
        CLASSHUB_MARKDOWN_ALLOWED_IMAGE_HOSTS=["cdn.example.org"],
    )
    def test_render_markdown_blocks_images_for_disallowed_host(self):
        html = render_markdown_to_safe_html('![diagram](https://evil.example.org/d.png)')
        self.assertNotIn("<img", html)

    @override_settings(
        CLASSHUB_MARKDOWN_ALLOW_IMAGES=True,
        CLASSHUB_MARKDOWN_ALLOWED_IMAGE_HOSTS=[],
    )
    def test_render_markdown_allows_relative_images_when_enabled(self):
        html = render_markdown_to_safe_html("![diagram](/lesson-asset/12/download)")
        self.assertIn("<img", html)
        self.assertIn('src="/lesson-asset/12/download"', html)

    @override_settings(
        CLASSHUB_MARKDOWN_ALLOW_IMAGES=True,
        CLASSHUB_MARKDOWN_ALLOWED_IMAGE_HOSTS=[],
        CLASSHUB_ASSET_BASE_URL="https://assets.example.org",
    )
    def test_render_markdown_rewrites_relative_media_urls_to_asset_origin(self):
        html = render_markdown_to_safe_html(
            "![diagram](/lesson-asset/12/download)\n\n[Watch](/lesson-video/4/stream)"
        )
        self.assertIn('src="https://assets.example.org/lesson-asset/12/download"', html)
        self.assertIn('href="https://assets.example.org/lesson-video/4/stream"', html)


class UploadScanServiceTests(SimpleTestCase):
    @override_settings(CLASSHUB_UPLOAD_SCAN_ENABLED=False)
    def test_scan_disabled_returns_disabled(self):
        upload = SimpleUploadedFile("project.sb3", b"abc123")
        result = scan_uploaded_file(upload)
        self.assertEqual(result.status, "disabled")

    @override_settings(
        CLASSHUB_UPLOAD_SCAN_ENABLED=True,
        CLASSHUB_UPLOAD_SCAN_COMMAND="scanner-cli --check",
        CLASSHUB_UPLOAD_SCAN_TIMEOUT_SECONDS=5,
    )
    def test_scan_marks_clean_on_returncode_zero(self):
        upload = SimpleUploadedFile("project.sb3", b"abc123")
        with patch("hub.services.upload_scan.subprocess.run") as run_mock:
            run_mock.return_value.returncode = 0
            run_mock.return_value.stdout = ""
            run_mock.return_value.stderr = ""
            result = scan_uploaded_file(upload)
        self.assertEqual(result.status, "clean")

    @override_settings(
        CLASSHUB_UPLOAD_SCAN_ENABLED=True,
        CLASSHUB_UPLOAD_SCAN_COMMAND="scanner-cli --check",
        CLASSHUB_UPLOAD_SCAN_TIMEOUT_SECONDS=5,
    )
    def test_scan_marks_infected_on_returncode_one(self):
        upload = SimpleUploadedFile("project.sb3", b"abc123")
        with patch("hub.services.upload_scan.subprocess.run") as run_mock:
            run_mock.return_value.returncode = 1
            run_mock.return_value.stdout = "FOUND TEST VIRUS"
            run_mock.return_value.stderr = ""
            result = scan_uploaded_file(upload)
        self.assertEqual(result.status, "infected")


class UploadValidationServiceTests(SimpleTestCase):
    def test_validate_upload_content_accepts_valid_sb3_archive(self):
        error = validate_upload_content(_sample_sb3_upload(), ".sb3")
        self.assertEqual(error, "")

    def test_validate_upload_content_rejects_non_zip_sb3(self):
        upload = SimpleUploadedFile("project.sb3", b"not-a-zip")
        error = validate_upload_content(upload, ".sb3")
        self.assertIn("does not match .sb3", error)


class ContentLinksServiceTests(SimpleTestCase):
    def test_parse_course_lesson_url_handles_local_or_absolute_urls(self):
        self.assertEqual(
            parse_course_lesson_url("/course/piper_scratch_12_session/01-welcome-private-workflow"),
            ("piper_scratch_12_session", "01-welcome-private-workflow"),
        )
        self.assertEqual(
            parse_course_lesson_url(
                "https://lms.example.org/course/piper_scratch_12_session/01-welcome-private-workflow/"
            ),
            ("piper_scratch_12_session", "01-welcome-private-workflow"),
        )
        self.assertIsNone(parse_course_lesson_url("/teach/lessons"))

    def test_normalize_lesson_videos_sets_expected_source_types(self):
        videos = normalize_lesson_videos(
            {
                "videos": [
                    {"id": "yt", "title": "YouTube", "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"},
                    {"id": "native", "title": "Native", "url": "https://cdn.example.org/lesson.mp4"},
                    {"id": "link", "title": "Link", "url": "https://example.org/article"},
                ]
            }
        )
        self.assertEqual(videos[0]["source_type"], "youtube")
        self.assertEqual(videos[1]["source_type"], "native")
        self.assertEqual(videos[2]["source_type"], "link")

    def test_safe_filename_strips_unsafe_characters(self):
        self.assertEqual(safe_filename("../../Ada Lovelace?.png"), "Ada_Lovelace_.png")

    @override_settings(CLASSHUB_ASSET_BASE_URL="")
    def test_build_asset_url_uses_relative_path_without_base_url(self):
        self.assertEqual(build_asset_url("/lesson-asset/8/download"), "/lesson-asset/8/download")

    @override_settings(CLASSHUB_ASSET_BASE_URL="https://assets.example.org/")
    def test_build_asset_url_prefixes_configured_asset_origin(self):
        self.assertEqual(
            build_asset_url("/lesson-video/3/stream"),
            "https://assets.example.org/lesson-video/3/stream",
        )


class StudentSessionMiddlewareTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.classroom = Class.objects.create(name="Session Class", join_code="SESS1234")
        self.student = StudentIdentity.objects.create(classroom=self.classroom, display_name="Ada")
        self.middleware = StudentSessionMiddleware(lambda _request: HttpResponse("ok"))

    def _request_with_student_session(self, path: str):
        request = self.factory.get(path)
        session_middleware = SessionMiddleware(lambda _request: HttpResponse("ok"))
        session_middleware.process_request(request)
        request.session["student_id"] = self.student.id
        request.session["class_id"] = self.classroom.id
        request.session["class_epoch"] = self.classroom.session_epoch
        request.session.save()
        return request

    def test_healthz_path_skips_student_lookup_queries(self):
        request = self._request_with_student_session("/healthz")
        with self.assertNumQueries(0):
            self.middleware(request)
        self.assertIsNone(request.student)
        self.assertIsNone(request.classroom)

    def test_static_path_skips_student_lookup_queries(self):
        request = self._request_with_student_session("/static/app.css")
        with self.assertNumQueries(0):
            self.middleware(request)
        self.assertIsNone(request.student)
        self.assertIsNone(request.classroom)

    def test_admin_path_skips_student_lookup_queries(self):
        request = self._request_with_student_session("/admin/")
        with self.assertNumQueries(0):
            self.middleware(request)
        self.assertIsNone(request.student)
        self.assertIsNone(request.classroom)

    def test_student_path_uses_single_query_and_attaches_student_context(self):
        request = self._request_with_student_session("/student")
        with self.assertNumQueries(1):
            self.middleware(request)
        self.assertIsNotNone(request.student)
        self.assertIsNotNone(request.classroom)
        self.assertEqual(request.student.id, self.student.id)
        self.assertEqual(request.classroom.id, self.classroom.id)
