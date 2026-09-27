"""Local speech-to-text with faster-whisper (spec 5.3, 5.7). Runs on the server's CPU.

Audio is written to a temporary file only for the duration of the transcription and deleted
right after, unless the user opted in to keep it (``keep_audio``). The transcript goes back to
the user's own browser for confirmation; it is pseudonymised like any typed answer once they
send it.
"""

from __future__ import annotations

import tempfile
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol


class Transcriber(Protocol):
    def transcribe(self, audio_path: Path, language: str) -> str: ...


@dataclass(frozen=True)
class Transcript:
    text: str
    duration_s: float
    seconds_taken: float


class TranscriptionUnavailable(RuntimeError):
    pass


class WhisperTranscriber:
    def __init__(self, model_size: str) -> None:
        try:
            from faster_whisper import WhisperModel  # type: ignore[import-not-found]
        except ImportError as e:
            raise TranscriptionUnavailable(
                "Speech input needs the optional 'speech' dependencies: uv sync --group speech"
            ) from e
        self._model: Any = WhisperModel(model_size, device="cpu", compute_type="int8")

    def transcribe(self, audio_path: Path, language: str) -> str:
        segments, _info = self._model.transcribe(
            str(audio_path), language=language, vad_filter=True
        )
        return " ".join(s.text.strip() for s in segments).strip()


@lru_cache(maxsize=1)
def default_transcriber(model_size: str) -> Transcriber:
    return WhisperTranscriber(model_size)


MAX_AUDIO_BYTES = 25 * 1024 * 1024
AUDIO_MAGIC = (b"\x1aE\xdf\xa3", b"OggS", b"RIFF", b"ID3", b"\xff\xfb", b"fLaC")


def looks_like_audio(data: bytes) -> bool:
    return data[:4] in AUDIO_MAGIC or data[:3] in AUDIO_MAGIC or data[4:8] == b"ftyp"


def transcribe_bytes(
    transcriber: Transcriber,
    data: bytes,
    language: str,
    duration_s: float,
    *,
    keep_dir: Path | None = None,
) -> Transcript:
    if len(data) > MAX_AUDIO_BYTES:
        raise ValueError("Recording too long.")
    if not looks_like_audio(data):
        raise ValueError("This is not an audio recording.")
    started = time.monotonic()
    with tempfile.NamedTemporaryFile(suffix=".audio", delete=keep_dir is None) as f:
        f.write(data)
        f.flush()
        text = transcriber.transcribe(Path(f.name), language)
        if keep_dir is not None:
            keep_dir.mkdir(parents=True, exist_ok=True)
            Path(f.name).replace(keep_dir / Path(f.name).name)
    return Transcript(
        text=text,
        duration_s=round(duration_s, 1),
        seconds_taken=round(time.monotonic() - started, 2),
    )
