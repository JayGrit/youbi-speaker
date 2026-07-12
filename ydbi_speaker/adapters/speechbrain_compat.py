from __future__ import annotations

import contextlib
import importlib.machinery
import sys
import types


def _stub_module(name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__package__ = name.rpartition(".")[0]
    module.__file__ = "<optional speechbrain k2_fsa stub>"
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None)
    return module


def suppress_optional_k2_lazy_import() -> None:
    """Avoid importing SpeechBrain's optional k2 integration during stack inspection.

    SpeechBrain can register ``speechbrain.integrations.k2_fsa`` as a LazyModule.
    On Python 3.12, ``inspect.stack()`` may touch that object while librosa imports
    optional modules, which forces an unrelated k2 import and fails when k2 is not
    installed. The speaker service does not use the k2 integration.
    """

    name = "speechbrain.integrations.k2_fsa"
    module = sys.modules.get(name)
    if module is not None:
        module_type = type(module)
        if module_type.__name__ != "LazyModule" or module_type.__module__ != "speechbrain.utils.importutils":
            return

    stub = _stub_module(name)
    sys.modules[name] = stub
    parent = sys.modules.get("speechbrain.integrations")
    if parent is None:
        return
    if module is None or getattr(parent, "__dict__", {}).get("k2_fsa") is module:
        with contextlib.suppress(Exception):
            setattr(parent, "k2_fsa", stub)
