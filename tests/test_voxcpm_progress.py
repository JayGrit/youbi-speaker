from __future__ import annotations

import io
import sys
import types
import unittest
from contextlib import redirect_stdout

soundfile = types.ModuleType("soundfile")
soundfile.write = lambda *args, **kwargs: None
sys.modules.setdefault("soundfile", soundfile)

pydub = types.ModuleType("pydub")
pydub.AudioSegment = type("AudioSegment", (), {})
sys.modules.setdefault("pydub", pydub)

from ydbi_speaker.adapters.voxcpm import _PROGRESS_LABEL, _chinese_progress


class VoxcpmProgressTest(unittest.TestCase):
    def test_progress_contains_segment_label_without_metrics(self) -> None:
        output = io.StringIO()
        token = _PROGRESS_LABEL.set("narration-4:26")
        try:
            with redirect_stdout(output):
                progress = _chinese_progress(range(5))
                for _ in progress:
                    pass
        finally:
            _PROGRESS_LABEL.reset(token)

        rendered = output.getvalue()
        self.assertIn("正在生成语音 narration-4:26: 100%", rendered)
        self.assertNotIn("5/5", rendered)
        self.assertNotIn("[", rendered)
        self.assertNotIn("步/s", rendered)


if __name__ == "__main__":
    unittest.main()
