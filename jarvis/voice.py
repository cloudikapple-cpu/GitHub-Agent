"""Voice input (speech-to-text) and output (text-to-speech).

Everything is optional and lazily imported, so a text-only install keeps
working.

STT engines
-----------

* ``auto``    - Groq when ``GROQ_API_KEY`` is set, local faster-whisper otherwise.
* ``groq``    - Groq's hosted Whisper API: fastest and the most accurate for
  Russian, needs a key and an internet connection.
* ``whisper`` - faster-whisper, fully offline, needs the model downloaded once.
* ``google``  - SpeechRecognition, online, no key.
* ``vosk``    - offline and lightweight, lower quality.

TTS engines: ``pyttsx3`` (offline) or ``none``.

Install::

    pip install "jarvis-desktop[voice]"   # microphone + local whisper + speech

Groq needs no extra package beyond ``requests``: put ``GROQ_API_KEY`` in
``.env`` (or ``keyring:GROQ_API_KEY`` in config.yaml) and set ``voice.stt:
groq``.
"""

from __future__ import annotations

import logging
import os
import tempfile
import wave
from pathlib import Path

SAMPLE_RATE = 16000
LOGGER = logging.getLogger("jarvis.voice")

#: Groq's OpenAI-compatible transcription endpoint.
GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
#: Turbo is the fast one; ``whisper-large-v3`` is slightly better and slower.
GROQ_DEFAULT_MODEL = "whisper-large-v3-turbo"
#: Local model names, so a Groq model name is not passed to faster-whisper.
LOCAL_WHISPER_MODELS = (
    "tiny",
    "base",
    "small",
    "medium",
    "large",
    "large-v2",
    "large-v3",
    "distil-large-v3",
)


class VoiceError(RuntimeError):
    """Raised when a voice backend is unavailable or fails."""


def groq_api_key(config=None) -> str:
    """Return the Groq key from the config, the keychain or the environment."""

    raw = str(getattr(config, "stt_api_key", "") or "")
    if raw:
        try:
            from .secrets import resolve

            return str(resolve(raw))
        except Exception:  # noqa: BLE001 - a missing keychain is not fatal here
            return raw
    return os.getenv("GROQ_API_KEY", "")


class VoiceIO:
    """Record speech, transcribe it, and speak replies back."""

    def __init__(self, config=None):
        from .config import VoiceConfig

        self.config = config or VoiceConfig()
        self._whisper = None
        self._tts = None

    # -- engine selection ----------------------------------------------
    def engine(self) -> str:
        """Resolve the configured engine, expanding ``auto``."""

        name = (self.config.stt or "auto").lower()
        if name != "auto":
            return name
        return "groq" if groq_api_key(self.config) else "whisper"

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

        try:
            frames = sd.rec(
                int(duration * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="int16"
            )
            sd.wait()
        except Exception as exc:  # noqa: BLE001 - device errors are wildly varied
            raise VoiceError(f"The microphone could not be read: {exc}") from exc

        path = Path(tempfile.gettempdir()) / "jarvis_input.wav"
        with wave.open(str(path), "wb") as fh:
            fh.setnchannels(1)
            fh.setsampwidth(2)
            fh.setframerate(SAMPLE_RATE)
            fh.writeframes(frames.tobytes())
        return path

    # -- transcription -------------------------------------------------
    def transcribe(self, wav_path: str | Path) -> str:
        engine = self.engine()
        path = Path(wav_path)
        if engine == "groq":
            try:
                return self._transcribe_groq(path)
            except VoiceError as exc:
                # Losing the network should not lose the recording: keep going
                # with the offline engine when it is installed.
                LOGGER.warning("Groq transcription failed (%s); trying faster-whisper", exc)
                return self._transcribe_whisper(path)
        if engine == "whisper":
            return self._transcribe_whisper(path)
        if engine == "vosk":
            return self._transcribe_vosk(path)
        return self._transcribe_speech_recognition(path)

    # -- groq ------------------------------------------------------------
    def groq_model(self) -> str:
        """Model name for Groq, ignoring local faster-whisper sizes."""

        configured = str(getattr(self.config, "stt_model", "") or "")
        if configured:
            return configured
        model = str(self.config.whisper_model or "")
        if model and model.lower() not in LOCAL_WHISPER_MODELS:
            return model
        return GROQ_DEFAULT_MODEL

    def _transcribe_groq(self, path: Path) -> str:
        key = groq_api_key(self.config)
        if not key:
            raise VoiceError(
                "Groq transcription needs a key. Add GROQ_API_KEY to .env "
                "(free keys: https://console.groq.com/keys)."
            )
        try:
            import requests
        except ImportError as exc:  # pragma: no cover - requests is a hard dependency
            raise VoiceError("Groq transcription needs 'requests'.") from exc

        data = {"model": self.groq_model(), "response_format": "json"}
        language = (self.config.language or "").strip()
        if language and language.lower() != "auto":
            data["language"] = language
        try:
            with path.open("rb") as fh:
                response = requests.post(
                    GROQ_URL,
                    headers={"Authorization": f"Bearer {key}"},
                    files={"file": (path.name, fh, "audio/wav")},
                    data=data,
                    timeout=120,
                )
        except OSError as exc:
            raise VoiceError(f"The recording could not be sent to Groq: {exc}") from exc
        if response.status_code == 401:
            raise VoiceError("Groq rejected the key. Check GROQ_API_KEY.")
        if response.status_code >= 400:
            raise VoiceError(f"Groq returned HTTP {response.status_code}.")
        try:
            return str(response.json().get("text", "")).strip()
        except ValueError as exc:
            raise VoiceError("Groq returned a response that is not JSON.") from exc

    # -- local engines ----------------------------------------------------
    def _local_whisper_model(self) -> str:
        model = str(self.config.whisper_model or "base")
        return model if model.lower() in LOCAL_WHISPER_MODELS else "base"

    def _transcribe_whisper(self, path: Path) -> str:
        if self._whisper is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise VoiceError(
                    "Local transcription needs 'faster-whisper'. Install with "
                    "`pip install \"jarvis-desktop[voice]\"`, or set voice.stt to "
                    "'groq' and put GROQ_API_KEY in .env."
                ) from exc
            self._whisper = WhisperModel(self._local_whisper_model(), compute_type="int8")
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
            LOGGER.debug("Text to speech failed", exc_info=True)


def available() -> bool:
    """True when at least microphone capture is installed."""

    try:
        import sounddevice  # noqa: F401
    except ImportError:
        return False
    return True


def transcription_available(config=None) -> bool:
    """True when some engine can turn the recording into text."""

    if groq_api_key(config):
        return True
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True
