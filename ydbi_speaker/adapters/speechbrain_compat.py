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


def _is_speechbrain_lazy_module(module: object) -> bool:
    module_type = type(module)
    return module_type.__name__ == "LazyModule" and module_type.__module__ == "speechbrain.utils.importutils"


def _replace_lazy_module(name: str, module: object | None) -> None:
    stub = _stub_module(name)
    sys.modules[name] = stub
    parent_name, _separator, attribute_name = name.rpartition(".")
    parent = sys.modules.get(parent_name)
    if parent is None:
        return
    if module is None or getattr(parent, "__dict__", {}).get(attribute_name) is module:
        with contextlib.suppress(Exception):
            setattr(parent, attribute_name, stub)


def suppress_optional_k2_lazy_import() -> None:
    """Avoid importing SpeechBrain's optional integrations during stack inspection.

    SpeechBrain can register optional integrations as LazyModule objects.
    On Python 3.12, ``inspect.stack()`` may touch that object while librosa imports
    optional modules, which forces unrelated integrations to import and fail when
    optional dependencies are not installed. The speaker service does not use
    SpeechBrain integrations.
    """

    lazy_module_names = [
        name
        for name, module in list(sys.modules.items())
        if name.startswith("speechbrain.integrations.") and _is_speechbrain_lazy_module(module)
    ]
    if "speechbrain.integrations.k2_fsa" not in lazy_module_names:
        lazy_module_names.append("speechbrain.integrations.k2_fsa")

    for name in lazy_module_names:
        module = sys.modules.get(name)
        if module is None or _is_speechbrain_lazy_module(module):
            _replace_lazy_module(name, module)
