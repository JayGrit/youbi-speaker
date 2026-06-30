from __future__ import annotations

import contextlib
import sys


def suppress_optional_k2_lazy_import() -> None:
    """Avoid importing SpeechBrain's optional k2 integration during stack inspection.

    SpeechBrain can register ``speechbrain.integrations.k2_fsa`` as a LazyModule.
    On Python 3.12, ``inspect.stack()`` may touch that object while librosa imports
    optional modules, which forces an unrelated k2 import and fails when k2 is not
    installed. The speaker service does not use the k2 integration.
    """

    name = "speechbrain.integrations.k2_fsa"
    module = sys.modules.get(name)
    if module is None:
        return

    module_type = type(module)
    if module_type.__name__ != "LazyModule" or module_type.__module__ != "speechbrain.utils.importutils":
        return

    sys.modules.pop(name, None)
    parent = sys.modules.get("speechbrain.integrations")
    if parent is not None and getattr(parent, "__dict__", {}).get("k2_fsa") is module:
        with contextlib.suppress(Exception):
            delattr(parent, "k2_fsa")
