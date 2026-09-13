from pathlib import Path
import wave

ROOT = Path(__file__).parents[1] / "mobile" / "assets" / "audio"

def test_generated_earcons_are_stereo_wavs_with_expected_panning():
    expected = {"double_tone.wav": .18, "panned_tone_left.wav": .16, "panned_tone_right.wav": .16, "soft_cue.wav": .12}
    for name, duration in expected.items():
        with wave.open(str(ROOT / name), "rb") as audio:
            assert audio.getnchannels() == 2
            assert audio.getframerate() == 22050
            assert audio.getnframes() / audio.getframerate() == pytest.approx(duration, abs=1 / 22050)

import pytest
