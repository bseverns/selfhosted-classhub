from types import SimpleNamespace

from django.test import SimpleTestCase

from .services.markdown_content import (
    render_markdown_to_safe_html,
    split_lesson_markdown_for_audiences,
)
from .services.content_links import (
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
