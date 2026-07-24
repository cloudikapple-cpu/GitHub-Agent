"""Voice input (speech-to-text) and output (text-to-speech).

Everything is optional and lazily imported, so a text-only install keeps
working. Recommended offline stack::

    pip install "jarvis-desktop[voice]"   # faster-whisper + sounddevice + pyttsx3

STT engines: ``whisper`` (faster-whisper, offline), ``google``
(SpeechRecognition, online), ``vosk`` (offline, lightweight).
TTS engines: ``pyttsx3`` (offline) or ``none``.
"""

from __future__ import annotations

import tempfile
import wave
from pathlib import Path

SAMPLE_RATE = 16000


class VoiceError(RuntimeError):
    """Raised when a voice backend is unavailable or fails."""


class VoiceIO:
    """Record speech, transcribe it, and speak replies back."""

    def __init__(self, config=None):
        from .config import VoiceConfig

        self.config = config or VoiceConfig()
        self._whisper = None
        self._tts = None

    # -- recording -----------------------------------------------------
    def record(self, seconds: float | None = None) -> Path:
        """Record microphone audio to a temporary WAV file."""

        duration = float(seconds or self.config.record_seconds)
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise VoiceError(
                "Microphone capture needs 'sounddevice'. Install with "
                "`pip install \"jarvis-desktop[voice]\"`."
            ) from exc

        frames = sd.rec(
            int(duration * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="int16"
        )
        sd.wait()

        path = Path(tempfile.gettempdir()) / "jarvis_input.wav"
        with wave.open(str(path), "wb") as fh:
            fh.setnchannels(1)
            fh.setsampwidth(2)
            fh.setframerate(SAMPLE_RATE)
            fh.writeframes(frames.tobytes())
        return path

    # -- transcription -------------------------------------------------
    def transcribe(self, wav_path: str | Path) -> str:
        engine = (self.config.stt or "whisper").lower()
        if engine == "whisper":
            return self._transcribe_whisper(Path(wav_path))
        if engine == "vosk":
            return self._transcribe_vosk(Path(wav_path))
        return self._transcribe_speech_recognition(Path(wav_path))

    def _transcribe_whisper(self, path: Path) -> str:
        if self._whisper is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise VoiceError(
                    "Local transcription needs 'faster-whisper'. Install with "
                    "`pip install \"jarvis-desktop[voice]\"`."
                ) from exc
            self._whisper = WhisperModel(self.config.whisper_model, compute_type="int8")
        segments, _info = self._whisper.transcribe(str(path), language=self.config.language)
        return " ".join(segment.text.strip() for segment in segments).strip()

    def _transcribe_speech_recognition(self, path: Path) -> str:
        try:
            import speech_recognition as sr
        except ImportError as exc:
            raise VoiceError("Online transcription needs 'SpeechRecognition'.") from exc
        recognizer = sr.Recognizer()
        with sr.AudioFile(str(path)) as source:
            audio = recognizer.record(source)
        return recognizer.recognize_google(audio, language=self.config.language)

    def _transcribe_vosk(self, path: Path) -> str:
        try:
            import json

            from vosk import KaldiRecognizer, Model
        except ImportError as exc:
            raise VoiceError("Offline transcription needs 'vosk'.") from exc
        model = Model(lang=self.config.language)
        with wave.open(str(path), "rb") as fh:
            recognizer = KaldiRecognizer(model, fh.getframerate())
            while True:
                data = fh.readframes(4000)
                if not data:
                    break
                recognizer.AcceptWaveform(data)
        return json.loads(recognizer.FinalResult()).get("text", "")

    def listen(self, seconds: float | None = None) -> str:
        """Record and transcribe in one step."""

        return self.transcribe(self.record(seconds))

    # -- speech --------------------------------------------------------
    def speak(self, text: str) -> None:
        """Say ``text`` out loud (no-op when TTS is disabled/unavailable)."""

        if not text or (self.config.tts or "none").lower() == "none":
            return
        try:
            import pyttsx3
        except ImportError:
            return
        try:
            if self._tts is None:
                self._tts = pyttsx3.init()
            self._tts.say(text)
            self._tts.runAndWait()
        except Exception:  # noqa: BLE001 - speech must never break a run
            pass


def available() -> bool:
    """True when at least microphone capture is installed."""

    try:
        import sounddevice  # noqa: F401
    except ImportError:
        return False
    return True
