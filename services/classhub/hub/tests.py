import json
from io import StringIO
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase
from django.utils import timezone

from .models import AuditEvent, Class, LessonRelease, Material, Module, StudentEvent, StudentIdentity, Submission


class TeacherPortalTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            username="teacher",
            password="pw12345",
            is_staff=True,
            is_superuser=True,
        )

    def _build_lesson_with_submission(self):
        classroom = Class.objects.create(name="Period 1", join_code="ABCD1234")
        module = Module.objects.create(classroom=classroom, title="Session 1", order_index=0)
        Material.objects.create(
            module=module,
            title="Session 1 lesson",
            type=Material.TYPE_LINK,
            url="/course/piper_scratch_12_session/01-welcome-private-workflow",
            order_index=0,
        )
        upload = Material.objects.create(
            module=module,
            title="Upload your project file",
            type=Material.TYPE_UPLOAD,
            accepted_extensions=".sb3",
            max_upload_mb=50,
            order_index=1,
        )
        student_a = StudentIdentity.objects.create(classroom=classroom, display_name="Ada")
        StudentIdentity.objects.create(classroom=classroom, display_name="Ben")
        Submission.objects.create(
            material=upload,
            student=student_a,
            original_filename="project.sb3",
            file=SimpleUploadedFile("project.sb3", b"dummy"),
        )
        return classroom, upload

    def test_teach_lessons_requires_staff(self):
        resp = self.client.get("/teach/lessons")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/admin/login/", resp["Location"])

    def test_teach_lessons_shows_submission_progress(self):
        classroom, upload = self._build_lesson_with_submission()
        self.client.force_login(self.staff)

        resp = self.client.get(f"/teach/lessons?class_id={classroom.id}")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Session 1 lesson")
        self.assertContains(resp, "Submitted 1 / 2")
        self.assertContains(resp, "Review missing now (1)")
        self.assertContains(resp, f"/teach/material/{upload.id}/submissions")
        self.assertContains(resp, f"/teach/material/{upload.id}/submissions?show=missing")
        self.assertContains(resp, f"/teach/material/{upload.id}/submissions?download=zip_latest")

    def test_teach_home_shows_recent_submissions(self):
        self._build_lesson_with_submission()
        self.client.force_login(self.staff)

        resp = self.client.get("/teach")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Recent submissions")
        self.assertContains(resp, "Ada")

    def test_teacher_logout_ends_staff_session(self):
        self.client.force_login(self.staff)
        resp = self.client.get("/teach/logout")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/admin/login/")
        self.assertIsNone(self.client.session.get("_auth_user_id"))

        denied = self.client.get("/teach")
        self.assertEqual(denied.status_code, 302)
        self.assertIn("/admin/login/", denied["Location"])


class CreateTeacherCommandTests(TestCase):
    def test_create_teacher_defaults_to_staff_non_superuser(self):
        out = StringIO()
        call_command(
            "create_teacher",
            username="teacher1",
            email="teacher1@example.org",
            password="pw12345",
            stdout=out,
        )

        user = get_user_model().objects.get(username="teacher1")
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.is_active)
        self.assertTrue(user.check_password("pw12345"))
        self.assertEqual(user.email, "teacher1@example.org")
        self.assertIn("Created teacher", out.getvalue())

    def test_create_teacher_existing_without_update_errors(self):
        get_user_model().objects.create_user(username="teacher1", password="pw12345")
        with self.assertRaises(CommandError):
            call_command("create_teacher", username="teacher1", password="newpass")

    def test_create_teacher_update_changes_password_and_status(self):
        user = get_user_model().objects.create_user(
            username="teacher1",
            email="old@example.org",
            password="oldpass",
            is_staff=False,
            is_superuser=False,
            is_active=True,
        )
        self.assertFalse(user.is_staff)

        out = StringIO()
        call_command(
            "create_teacher",
            username="teacher1",
            password="newpass",
            update=True,
            inactive=True,
            clear_email=True,
            stdout=out,
        )

        user.refresh_from_db()
        self.assertTrue(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_active)
        self.assertTrue(user.check_password("newpass"))
        self.assertEqual(user.email, "")
        self.assertIn("Updated teacher", out.getvalue())


class LessonReleaseTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            username="teacher_release",
            password="pw12345",
            is_staff=True,
            is_superuser=False,
        )
        self.classroom = Class.objects.create(name="Release Class", join_code="REL12345")
        self.module = Module.objects.create(classroom=self.classroom, title="Session 1", order_index=0)
        Material.objects.create(
            module=self.module,
            title="Session 1 lesson",
            type=Material.TYPE_LINK,
            url="/course/piper_scratch_12_session/s01-welcome-private-workflow",
            order_index=0,
        )
        self.upload = Material.objects.create(
            module=self.module,
            title="Homework dropbox",
            type=Material.TYPE_UPLOAD,
            accepted_extensions=".sb3",
            max_upload_mb=50,
            order_index=1,
        )
        self.student = StudentIdentity.objects.create(classroom=self.classroom, display_name="Ada")

    def _login_student(self):
        session = self.client.session
        session["student_id"] = self.student.id
        session["class_id"] = self.classroom.id
        session.save()

    def test_teacher_can_set_release_date_from_interface(self):
        self.client.force_login(self.staff)
        target_date = timezone.localdate() + timedelta(days=3)

        resp = self.client.post(
            "/teach/lessons/release",
            {
                "class_id": str(self.classroom.id),
                "course_slug": "piper_scratch_12_session",
                "lesson_slug": "s01-welcome-private-workflow",
                "action": "set_date",
                "available_on": target_date.isoformat(),
                "return_to": f"/teach/lessons?class_id={self.classroom.id}",
            },
        )
        self.assertEqual(resp.status_code, 302)

        row = LessonRelease.objects.get(
            classroom=self.classroom,
            course_slug="piper_scratch_12_session",
            lesson_slug="s01-welcome-private-workflow",
        )
        self.assertEqual(row.available_on, target_date)
        self.assertFalse(row.force_locked)

    def test_student_lesson_is_intro_only_before_release(self):
        LessonRelease.objects.create(
            classroom=self.classroom,
            course_slug="piper_scratch_12_session",
            lesson_slug="s01-welcome-private-workflow",
            available_on=timezone.localdate() + timedelta(days=2),
        )
        self._login_student()

        resp = self.client.get("/course/piper_scratch_12_session/s01-welcome-private-workflow")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "intro-only mode")
        self.assertNotContains(resp, "Homework dropbox")

    def test_student_upload_is_blocked_before_release(self):
        locked_until = timezone.localdate() + timedelta(days=2)
        LessonRelease.objects.create(
            classroom=self.classroom,
            course_slug="piper_scratch_12_session",
            lesson_slug="s01-welcome-private-workflow",
            available_on=locked_until,
        )
        self._login_student()

        resp = self.client.post(
            f"/material/{self.upload.id}/upload",
            {"file": SimpleUploadedFile("project.sb3", b"dummy")},
        )
        self.assertEqual(resp.status_code, 403)
        self.assertContains(resp, locked_until.isoformat())


class JoinClassTests(TestCase):
    def setUp(self):
        self.classroom = Class.objects.create(name="Join Test", join_code="JOIN1234")

    def test_join_same_name_without_return_code_creates_new_identity(self):
        payload = {"class_code": self.classroom.join_code, "display_name": "Ada"}
        r1 = self.client.post("/join", data=json.dumps(payload), content_type="application/json")
        self.assertEqual(r1.status_code, 200)
        first_id = self.client.session.get("student_id")
        first_event = StudentEvent.objects.order_by("-id").first()
        self.assertIsNotNone(first_event)
        self.assertEqual(first_event.event_type, StudentEvent.EVENT_CLASS_JOIN)

        # Simulate different machine/browser (no prior device cookie).
        other = Client()
        r2 = other.post("/join", data=json.dumps(payload), content_type="application/json")
        self.assertEqual(r2.status_code, 200)
        second_id = other.session.get("student_id")

        self.assertNotEqual(first_id, second_id)
        self.assertEqual(StudentIdentity.objects.filter(classroom=self.classroom).count(), 2)

    def test_join_same_device_without_return_code_reuses_identity(self):
        payload = {"class_code": self.classroom.join_code, "display_name": "Ada"}
        r1 = self.client.post("/join", data=json.dumps(payload), content_type="application/json")
        self.assertEqual(r1.status_code, 200)
        first_id = self.client.session.get("student_id")

        # Student logs out, then re-joins from the same browser/device.
        self.client.get("/logout")
        r2 = self.client.post("/join", data=json.dumps(payload), content_type="application/json")
        self.assertEqual(r2.status_code, 200)
        second_id = self.client.session.get("student_id")

        self.assertEqual(first_id, second_id)
        self.assertTrue(r2.json().get("rejoined"))
        self.assertEqual(StudentIdentity.objects.filter(classroom=self.classroom).count(), 1)
        event = StudentEvent.objects.order_by("-id").first()
        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, StudentEvent.EVENT_REJOIN_DEVICE_HINT)

    def test_join_same_device_with_different_name_creates_new_identity(self):
        payload = {"class_code": self.classroom.join_code, "display_name": "Ada"}
        r1 = self.client.post("/join", data=json.dumps(payload), content_type="application/json")
        self.assertEqual(r1.status_code, 200)
        first_id = self.client.session.get("student_id")

        self.client.get("/logout")
        r2 = self.client.post(
            "/join",
            data=json.dumps({"class_code": self.classroom.join_code, "display_name": "Ben"}),
            content_type="application/json",
        )
        self.assertEqual(r2.status_code, 200)
        second_id = self.client.session.get("student_id")

        self.assertNotEqual(first_id, second_id)
        self.assertFalse(r2.json().get("rejoined"))
        self.assertEqual(StudentIdentity.objects.filter(classroom=self.classroom).count(), 2)

    def test_join_reuses_identity_when_return_code_matches(self):
        r1 = self.client.post(
            "/join",
            data=json.dumps({"class_code": self.classroom.join_code, "display_name": "Ada"}),
            content_type="application/json",
        )
        self.assertEqual(r1.status_code, 200)
        first_id = self.client.session.get("student_id")
        first_code = r1.json().get("return_code")
        self.assertTrue(first_code)

        r2 = self.client.post(
            "/join",
            data=json.dumps(
                {
                    "class_code": self.classroom.join_code,
                    "display_name": "ada",
                    "return_code": first_code,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(r2.status_code, 200)
        second_id = self.client.session.get("student_id")
        self.assertTrue(r2.json().get("rejoined"))

        self.assertEqual(first_id, second_id)
        self.assertEqual(StudentIdentity.objects.filter(classroom=self.classroom).count(), 1)
        event = StudentEvent.objects.order_by("-id").first()
        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, StudentEvent.EVENT_REJOIN_RETURN_CODE)

    def test_join_with_invalid_return_code_is_rejected(self):
        resp = self.client.post(
            "/join",
            data=json.dumps(
                {
                    "class_code": self.classroom.join_code,
                    "display_name": "Ada",
                    "return_code": "ZZZZZZ",
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json().get("error"), "invalid_return_code")
        self.assertEqual(StudentIdentity.objects.filter(classroom=self.classroom).count(), 0)


class TeacherAuditTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            username="teacher_audit",
            password="pw12345",
            is_staff=True,
            is_superuser=False,
        )
        self.classroom = Class.objects.create(name="Audit Class", join_code="AUD12345")

    def test_teach_toggle_lock_creates_audit_event(self):
        self.client.force_login(self.staff)

        resp = self.client.post(f"/teach/class/{self.classroom.id}/toggle-lock")
        self.assertEqual(resp.status_code, 302)

        event = AuditEvent.objects.filter(action="class.toggle_lock").first()
        self.assertIsNotNone(event)
        self.assertEqual(event.classroom_id, self.classroom.id)
        self.assertEqual(event.actor_user_id, self.staff.id)


class SubmissionRetentionCommandTests(TestCase):
    def setUp(self):
        classroom = Class.objects.create(name="Retention Class", join_code="RET12345")
        module = Module.objects.create(classroom=classroom, title="Session 1", order_index=0)
        material = Material.objects.create(
            module=module,
            title="Upload",
            type=Material.TYPE_UPLOAD,
            accepted_extensions=".sb3",
            max_upload_mb=50,
            order_index=0,
        )
        student = StudentIdentity.objects.create(classroom=classroom, display_name="Ada")

        self.old = Submission.objects.create(
            material=material,
            student=student,
            original_filename="old.sb3",
            file=SimpleUploadedFile("old.sb3", b"old"),
        )
        self.new = Submission.objects.create(
            material=material,
            student=student,
            original_filename="new.sb3",
            file=SimpleUploadedFile("new.sb3", b"new"),
        )
        Submission.objects.filter(id=self.old.id).update(uploaded_at=timezone.now() - timedelta(days=120))

    def test_prune_submissions_dry_run_keeps_rows(self):
        call_command("prune_submissions", older_than_days=90, dry_run=True)
        self.assertEqual(Submission.objects.count(), 2)

    def test_prune_submissions_deletes_old_rows(self):
        call_command("prune_submissions", older_than_days=90)
        ids = set(Submission.objects.values_list("id", flat=True))
        self.assertNotIn(self.old.id, ids)
        self.assertIn(self.new.id, ids)


class StudentEventRetentionCommandTests(TestCase):
    def setUp(self):
        self.classroom = Class.objects.create(name="Events Class", join_code="EVT12345")
        self.student = StudentIdentity.objects.create(classroom=self.classroom, display_name="Ada")
        self.old = StudentEvent.objects.create(
            classroom=self.classroom,
            student=self.student,
            event_type=StudentEvent.EVENT_CLASS_JOIN,
            source="test",
            details={},
        )
        self.new = StudentEvent.objects.create(
            classroom=self.classroom,
            student=self.student,
            event_type=StudentEvent.EVENT_SUBMISSION_UPLOAD,
            source="test",
            details={},
        )
        StudentEvent.objects.filter(id=self.old.id).update(created_at=timezone.now() - timedelta(days=120))

    def test_prune_student_events_dry_run_keeps_rows(self):
        call_command("prune_student_events", older_than_days=90, dry_run=True)
        self.assertEqual(StudentEvent.objects.count(), 2)

    def test_prune_student_events_deletes_old_rows(self):
        call_command("prune_student_events", older_than_days=90)
        ids = set(StudentEvent.objects.values_list("id", flat=True))
        self.assertNotIn(self.old.id, ids)
        self.assertIn(self.new.id, ids)


class StudentEventSubmissionTests(TestCase):
    def setUp(self):
        self.classroom = Class.objects.create(name="Uploads Class", join_code="UPL12345")
        self.module = Module.objects.create(classroom=self.classroom, title="Session 1", order_index=0)
        self.material = Material.objects.create(
            module=self.module,
            title="Upload your project",
            type=Material.TYPE_UPLOAD,
            accepted_extensions=".sb3",
            max_upload_mb=50,
            order_index=0,
        )
        self.student = StudentIdentity.objects.create(classroom=self.classroom, display_name="Ada")

    def _login_student(self):
        session = self.client.session
        session["student_id"] = self.student.id
        session["class_id"] = self.classroom.id
        session.save()

    def test_material_upload_emits_student_event(self):
        self._login_student()
        resp = self.client.post(
            f"/material/{self.material.id}/upload",
            {
                "file": SimpleUploadedFile("project.sb3", b"dummy"),
                "note": "done",
            },
        )
        self.assertEqual(resp.status_code, 302)

        event = StudentEvent.objects.filter(event_type=StudentEvent.EVENT_SUBMISSION_UPLOAD).order_by("-id").first()
        self.assertIsNotNone(event)
        self.assertEqual(event.classroom_id, self.classroom.id)
        self.assertEqual(event.student_id, self.student.id)
        self.assertEqual(int(event.details.get("material_id") or 0), self.material.id)
