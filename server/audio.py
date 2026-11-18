"""Small WAV helpers (stdlib only)."""
from __future__ import annotations

import io
import math
import struct
import wave


def tone_wav(text: str, rate: int = 16000) -> bytes:
    """Mock TTS: a soft two-note chime whose length scales with the reply, so the
    device/web player has real audio to play without any API."""
    dur = min(0.25 + 0.03 * len(text), 2.5)
    n = int(rate * dur)
    frames = bytearray()
    for i in range(n):
        t = i / rate
        f = 660 if t < dur / 2 else 880
        env = min(1.0, i / 400, (n - i) / 800)
        frames += struct.pack("<h", int(6000 * env * math.sin(2 * math.pi * f * t)))
    return pcm16_to_wav(bytes(frames), rate)


def pcm16_to_wav(pcm: bytes, rate: int = 16000, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def silence_wav(seconds: float = 0.5, rate: int = 16000) -> bytes:
    return pcm16_to_wav(b"\x00\x00" * int(rate * seconds), rate)


def sniff_mime(data: bytes) -> tuple[str, str]:
    """(filename, mime) for the STT multipart upload."""
    if data[:4] == b"RIFF":
        return "audio.wav", "audio/wav"
    if data[:4] == b"\x1aE\xdf\xa3":
        return "audio.webm", "audio/webm"
    if data[:4] == b"OggS":
        return "audio.ogg", "audio/ogg"
    if data[:3] == b"ID3" or data[:2] == b"\xff\xfb":
        return "audio.mp3", "audio/mpeg"
    if data[4:8] == b"ftyp":
        return "audio.m4a", "audio/mp4"
    return "audio.wav", "audio/wav"
