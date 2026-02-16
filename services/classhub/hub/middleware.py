"""Student session middleware.

This is the central trick that makes class-code auth feel like a real login.

- Teachers use Django auth.
- Students are tracked by a session cookie containing student_id + class_id.

Later, this becomes the access-control boundary for the helper and for content.
"""

from .models import StudentIdentity, Class

class StudentSessionMiddleware:
    """Attach learner context to each request if a student session exists.

    Why this exists:
    - Django already attaches `request.user` for teacher/admin auth.
    - Student auth in this MVP is session-based (class code + display name),
      so we also attach:
      - `request.student`
      - `request.classroom`
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Default state for anonymous/teacher requests.
        request.student = None
        request.classroom = None

        # Student identity is stored in the session after `/join`.
        sid = request.session.get("student_id")
        cid = request.session.get("class_id")

        if sid and cid:
            # Resolve both records on each request so downstream views can rely
            # on object-level access without repeating session parsing.
            request.student = StudentIdentity.objects.filter(id=sid, classroom_id=cid).first()
            request.classroom = Class.objects.filter(id=cid).first()

        return self.get_response(request)
