"""Compatibility export surface for hub.views.

New code should import endpoints from submodules by concern:
- hub.views.student
- hub.views.teacher
- hub.views.content
- hub.views.media
"""

# Keep legacy module importable without polluting the active endpoint surface.
from . import _legacy as legacy  # noqa: F401

# Export concern-based endpoint modules last so they are the active callables.
from .content import *  # noqa: F401,F403
from .internal import *  # noqa: F401,F403
from .media import *  # noqa: F401,F403
from .student import *  # noqa: F401,F403
from .teacher import *  # noqa: F401,F403
