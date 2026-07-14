from __future__ import annotations

import contextlib
import importlib.machinery
import sys
import types

_OPTIONAL_INTEGRATIONS = (
    "speechbrain.integrations.k2_fsa",
    "speechbrain.integrations.nlp",
)


def _stub_module(name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__package__ = name.rpartition(".")[0]
    module.__file__ = f"<optional {name} stub>"
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None)
    return module


def _is_speechbrain_lazy_module(module: object) -> bool:
    module_type = type(module)
    return module_type.__name__ == "LazyModule" and module_type.__module__ == "speechbrain.utils.importutils"


def _lazy_module_target(module: object) -> str | None:
    try:
        module_dict = object.__getattribute__(module, "__dict__")
    except Exception:
        return None
    for key in ("target", "_target", "module_name", "__name__"):
        value = module_dict.get(key)
        if isinstance(value, str):
            return value
    return None


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


def suppress_optional_speechbrain_integrations() -> None:
    """Avoid importing SpeechBrain's optional integrations during stack inspection.

    SpeechBrain can register optional integrations as LazyModule objects.
    On Python 3.12, ``inspect.stack()`` may touch that object while librosa imports
    optional modules, which forces unrelated integrations to import and fail when
    optional dependencies are not installed. The speaker service does not use
    SpeechBrain integrations.
    """

    lazy_module_names = set(_OPTIONAL_INTEGRATIONS)
    for name, module in list(sys.modules.items()):
        if name.startswith("speechbrain.integrations.") and _is_speechbrain_lazy_module(module):
            lazy_module_names.add(name)

    integrations = sys.modules.get("speechbrain.integrations")
    if integrations is not None:
        try:
            integration_attrs = object.__getattribute__(integrations, "__dict__")
        except Exception:
            integration_attrs = {}
        for attribute, module in list(integration_attrs.items()):
            if not _is_speechbrain_lazy_module(module):
                continue
            target = _lazy_module_target(module)
            if target and target.startswith("speechbrain.integrations."):
                lazy_module_names.add(target)
                continue
            if not attribute.startswith("_"):
                lazy_module_names.add(f"speechbrain.integrations.{attribute}")

    for name in lazy_module_names:
        module = sys.modules.get(name)
        if module is None or _is_speechbrain_lazy_module(module):
            _replace_lazy_module(name, module)


def suppress_optional_k2_lazy_import() -> None:
    suppress_optional_speechbrain_integrations()
