"""Compatibility export surface for hub.views.

New code should import endpoints from submodules by concern:
- hub.views.student
- hub.views.teacher
- hub.views.content
- hub.views.media
"""

# Keep legacy internals importable for downstream callers during migration.
from ._legacy import *  # noqa: F401,F403

# Export concern-based endpoint modules last so they are the active callables.
from .content import *  # noqa: F401,F403
from .media import *  # noqa: F401,F403
from .student import *  # noqa: F401,F403
from .teacher import *  # noqa: F401,F403
