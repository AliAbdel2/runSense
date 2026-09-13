"""Generate small stereo WAV earcons used by the mobile triage path."""
from pathlib import Path
import math
import struct
import wave

OUT = Path(__file__).resolve().parents[1] / "mobile" / "assets" / "audio"
RATE = 22050

def tone(path: Path, duration: float, frequencies: list[float], pan: float = 0.0) -> None:
    samples = int(RATE * duration)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(2); out.setsampwidth(2); out.setframerate(RATE)
        frames = []
        for i in range(samples):
            t = i / RATE; fade = min(1.0, i / (RATE * .01), (samples - i) / (RATE * .02))
            value = sum(math.sin(2 * math.pi * f * t) for f in frequencies) / len(frequencies) * fade
            left = int(12000 * value * (1 - max(pan, 0)))
            right = int(12000 * value * (1 + min(pan, 0)))
            frames.append(struct.pack("<hh", left, right))
        out.writeframes(b"".join(frames))

def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tone(OUT / "double_tone.wav", .18, [880, 660])
    tone(OUT / "panned_tone_left.wav", .16, [660], pan=-1)
    tone(OUT / "panned_tone_right.wav", .16, [660], pan=1)
    tone(OUT / "soft_cue.wav", .12, [440], pan=0)

if __name__ == "__main__": main()
