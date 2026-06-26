from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pydub.generators import Sine

from ydbi_speaker.adapters import reference


class ReferenceSelectionTest(unittest.TestCase):
    def _tone(self, duration_ms: int, directory: Path) -> Path:
        path = directory / f"tone-{duration_ms}.wav"
        Sine(440).to_audio_segment(duration=duration_ms).apply_gain(-18).export(path, format="wav")
        return path

    def test_reference_must_exceed_five_seconds(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            row = {"item_index": 1, "src_text": "This is a usable reference sentence."}

            exact_threshold = reference._metrics(self._tone(5000, directory), row)
            over_threshold = reference._metrics(self._tone(5001, directory), row)

        self.assertTrue(exact_threshold["disqualified"])
        self.assertEqual(0.0, exact_threshold["score"])
        self.assertFalse(over_threshold["disqualified"])
        self.assertGreater(over_threshold["score"], 0.0)

    def test_duration_score_increases_until_ten_seconds(self):
        self.assertLess(reference._duration_score(6000), reference._duration_score(8000))
        self.assertLess(reference._duration_score(8000), reference._duration_score(10000))
        self.assertEqual(30.0, reference._duration_score(10000))


if __name__ == "__main__":
    unittest.main()
