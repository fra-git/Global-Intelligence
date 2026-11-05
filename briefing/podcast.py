"""Daily podcast: an Italian spoken script written by Claude from the finished report,
read aloud by a free local voice (Piper) and sent to Telegram as an audio file.

No extra research is done: the script is written from the report's own text, so the
cost is one writing run. Speech synthesis runs on the GitHub runner and uses no Claude.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

from briefing.config import ROOT

log = logging.getLogger(__name__)

PROMPT_PATH = ROOT / "prompts" / "podcast_prompt.md"
SAMPLE_PATH = ROOT / "config" / "podcast_sample_it.txt"
VOICE_DIR = Path(os.environ.get("BRIEFING_VOICE_DIR", ROOT / "voices"))
DEFAULT_VOICE = os.environ.get("BRIEFING_VOICE", "it_IT-paola-medium")

# Spoken minutes per day kind (see dispatch.day_kind). Measured on the runner: Paola reads
# ~183 words a minute at normal speed; slowed by LENGTH_SCALE it reads ~170.
PODCAST_MINUTES = {"weekday": 17, "saturday": 25, "sunday": 25}
SPOKEN_WPM = 170
LENGTH_SCALE = 1.08
_PARAGRAPH_PAUSE_S = 0.6

_MD = [
    (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),   # links -> their text
    (re.compile(r"https?://\S+"), ""),
    (re.compile(r"^\s*#{1,6}\s*", re.MULTILINE), ""),
    (re.compile(r"^\s*[-*•]\s+", re.MULTILINE), ""),
    (re.compile(r"[*_`>|]"), ""),
    (re.compile(r"[()\[\]]"), ", "),
]
_SYMBOLS = [("%", " per cento"), ("€", " euro"), ("$", " dollari"), ("&", " e "), ("/", " ")]


def load_prompt() -> str:
    return PROMPT_PATH.read_text()


def build_message(report_markdown: str, date_text: str, minutes: int) -> str:
    words = minutes * SPOKEN_WPM
    return (f"Date: {date_text}.\nWrite a podcast script of about {words} words "
            f"(about {minutes} minutes when read aloud). Cover the most important stories in "
            "proportion to their weight in the report.\n\n<report>\n"
            f"{report_markdown}\n</report>\n\nWrite the Italian script now.")


def speech_text(script: str) -> str:
    """Make a script safe for a speech engine: no markup, symbols said as words."""
    text = script
    for pattern, repl in _MD:
        text = pattern.sub(repl, text)
    for sym, word in _SYMBOLS:
        text = text.replace(sym, word)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ,", ",", text)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return "\n\n".join(paragraphs)


def ensure_voice(voice: str = DEFAULT_VOICE, directory: Path = VOICE_DIR) -> Path:
    model = directory / f"{voice}.onnx"
    if not model.exists():
        directory.mkdir(parents=True, exist_ok=True)
        subprocess.run([sys.executable, "-m", "piper.download_voices", voice,
                        "--download-dir", str(directory)], check=True)
    return model


def synthesize(text: str, voice: str = DEFAULT_VOICE, title: str = "") -> tuple[bytes, int]:
    """Read `text` aloud. Returns (MP3 bytes, duration in seconds)."""
    from piper import PiperVoice
    from piper.config import SynthesisConfig

    model = PiperVoice.load(str(ensure_voice(voice)))
    with tempfile.TemporaryDirectory(prefix="podcast-") as tmp:
        wav_path, mp3_path = Path(tmp) / "out.wav", Path(tmp) / "out.mp3"
        with wave.open(str(wav_path), "wb") as out:
            first = True
            for para in text.split("\n\n"):
                with tempfile.NamedTemporaryFile(suffix=".wav", dir=tmp, delete=False) as part:
                    with wave.open(part.name, "wb") as pw:
                        model.synthesize_wav(para, pw, SynthesisConfig(length_scale=LENGTH_SCALE))
                with wave.open(part.name, "rb") as pr:
                    if first:
                        out.setparams(pr.getparams())
                        first = False
                    out.writeframes(pr.readframes(pr.getnframes()))
                    silence = int(pr.getframerate() * _PARAGRAPH_PAUSE_S)
                    out.writeframes(b"\x00" * silence * pr.getsampwidth() * pr.getnchannels())
        with wave.open(str(wav_path), "rb") as w:
            seconds = round(w.getnframes() / w.getframerate())
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path), "-ac", "1",
                        "-b:a", "64k", "-metadata", f"title={title}",
                        "-metadata", "artist=Global Intelligence", str(mp3_path)], check=True)
        return mp3_path.read_bytes(), seconds
