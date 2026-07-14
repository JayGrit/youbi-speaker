from __future__ import annotations

import importlib.machinery
import sys
import types
import unittest

from ydbi_speaker.adapters.speechbrain_compat import suppress_optional_speechbrain_integrations


class LazyModule:
    target = "speechbrain.integrations.nlp"


LazyModule.__module__ = "speechbrain.utils.importutils"


class SpeechBrainCompatTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_modules = dict(sys.modules)

    def tearDown(self) -> None:
        sys.modules.clear()
        sys.modules.update(self._original_modules)

    def test_replaces_lazy_integration_parent_attribute(self) -> None:
        integrations = types.ModuleType("speechbrain.integrations")
        integrations.__package__ = "speechbrain"
        integrations.__spec__ = importlib.machinery.ModuleSpec("speechbrain.integrations", loader=None)
        integrations.nlp = LazyModule()
        sys.modules["speechbrain.integrations"] = integrations

        suppress_optional_speechbrain_integrations()

        self.assertIs(sys.modules["speechbrain.integrations.nlp"], integrations.nlp)
        self.assertEqual("<optional speechbrain.integrations.nlp stub>", integrations.nlp.__file__)
