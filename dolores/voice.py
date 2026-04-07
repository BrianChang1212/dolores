"""TTS: Piper (default, local) with edge-tts fallback (online)."""

import os
import re
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from typing import Optional

from .config import (
    DEFAULT_PIPER_VOICE,
    DEFAULT_TTS_BACKEND,
    get_piper_voices_dir,
    load_config,
)

MOOD_TAG_RE = re.compile(r"\[mood:\s*\w+\]", re.IGNORECASE)

try:
    from piper.download_voices import download_voice
    from piper import PiperVoice
    HAS_PIPER = True
except ImportError:
    HAS_PIPER = False

_piper_cached: Optional[tuple[str, "PiperVoice"]] = None

PIPER_VOICES_JSON = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/voices.json?download=true"
)

# Used when voices.json cannot be fetched
CURATED_PIPER_VOICES = [
    "zh_CN-huayan-medium",
    "zh_CN-huayan-x_low",
    "zh_CN-xiao_ya-medium",
    "zh_CN-chaowen-medium",
    "en_US-lessac-medium",
    "en_US-amy-medium",
    "en_GB-alan-medium",
    "en_GB-alba-medium",
]


def _clean_for_tts(text: str) -> str:
    text = MOOD_TAG_RE.sub("", text)
    text = re.sub(r"\[/?[a-z_]+.*?\]", "", text)
    return text.strip()


def piper_available() -> bool:
    return HAS_PIPER


def default_piper_voice() -> str:
    return DEFAULT_PIPER_VOICE


def _piper_model_paths(voice_id: str, voices_dir: Path) -> tuple[Path, Path]:
    onnx = voices_dir / f"{voice_id}.onnx"
    json_path = voices_dir / f"{voice_id}.onnx.json"
    return onnx, json_path


def ensure_piper_voice(voice_id: str) -> Optional[Path]:
    """Download voice if missing; return path to .onnx or None on failure."""
    if not HAS_PIPER:
        return None
    voices_dir = get_piper_voices_dir()
    onnx, _ = _piper_model_paths(voice_id, voices_dir)
    try:
        if not onnx.exists() or onnx.stat().st_size == 0:
            download_voice(voice_id, voices_dir, force_redownload=False)
    except Exception:
        return None
    return onnx if onnx.exists() and onnx.stat().st_size > 0 else None


def clear_piper_voice_cache():
    """Call after switching Piper model so the next speak() loads the new voice."""
    global _piper_cached
    _piper_cached = None


def fetch_piper_voice_ids(prefix: str = "") -> list[str]:
    """
    List Piper voice ids from rhasspy/piper-voices (network).
    prefix e.g. 'zh_CN', 'en_US' — empty string returns all (can be long).
    """
    try:
        import json
        from urllib.request import urlopen

        with urlopen(PIPER_VOICES_JSON, timeout=25) as r:
            data = json.load(r)
        keys = sorted(data.keys())
        if prefix:
            keys = [k for k in keys if k.startswith(prefix)]
        return keys
    except Exception:
        if prefix:
            return [v for v in CURATED_PIPER_VOICES if v.startswith(prefix)]
        return list(CURATED_PIPER_VOICES)


def fetch_edge_voices(locale_prefix: str = "zh-TW") -> list[dict]:
    """
    List Edge TTS voices whose Locale or ShortName starts with locale_prefix.
    Each item: ShortName, Locale, FriendlyName, Gender, ...
    """
    try:
        import asyncio
        import edge_tts

        async def _list():
            return await edge_tts.list_voices()

        voices = asyncio.run(_list())
    except Exception:
        return []
    out = []
    for v in voices:
        sn = str(v.get("ShortName", ""))
        loc = str(v.get("Locale", ""))
        if sn.startswith(locale_prefix) or loc.startswith(locale_prefix):
            out.append(v)
    return sorted(out, key=lambda x: str(x.get("ShortName", "")))


def _get_piper_voice(model_path: Path) -> "PiperVoice":
    global _piper_cached
    key = str(model_path.resolve())
    if _piper_cached and _piper_cached[0] == key:
        return _piper_cached[1]
    voice = PiperVoice.load(model_path)
    _piper_cached = (key, voice)
    return voice


def _play_wav(wav_path: str):
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    import pygame
    pygame.mixer.init()
    pygame.mixer.music.load(wav_path)
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        pygame.time.wait(100)
    pygame.mixer.music.stop()
    pygame.mixer.quit()


def speak_piper(text: str, voice_id: Optional[str] = None) -> bool:
    """Synthesize with Piper and play. Returns False if Piper unavailable or failed."""
    cleaned = _clean_for_tts(text)
    if not cleaned or not HAS_PIPER:
        return False

    vid = voice_id or load_config().get("piper_voice") or default_piper_voice()
    onnx = ensure_piper_voice(vid)
    if not onnx:
        return False

    wav_path = os.path.join(tempfile.gettempdir(), "_dolores_piper.wav")
    try:
        pv = _get_piper_voice(onnx)
        with wave.open(wav_path, "wb") as wf:
            pv.synthesize_wav(cleaned, wf)
        _play_wav(wav_path)
        return True
    except Exception:
        return False
    finally:
        try:
            os.remove(wav_path)
        except OSError:
            pass


def speak_edge(text: str, voice: str) -> bool:
    cleaned = _clean_for_tts(text)
    if not cleaned:
        return False

    txt_path = os.path.join(tempfile.gettempdir(), "_dolores_tts_input.txt")
    mp3_path = os.path.join(tempfile.gettempdir(), "_dolores_voice.mp3")
    ok = False

    try:
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(cleaned)
    except OSError:
        return False

    script = _EDGE_SCRIPT.format(txt_path=txt_path, mp3_path=mp3_path, voice=voice)
    try:
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        r = subprocess.run([sys.executable, "-c", script], timeout=60, **kwargs)
        ok = r.returncode == 0
    except (subprocess.TimeoutExpired, Exception):
        ok = False
    finally:
        for p in (txt_path, mp3_path):
            try:
                os.remove(p)
            except OSError:
                pass
    return ok


_EDGE_SCRIPT = '''
import asyncio, os
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

async def main():
    txt_path = r"{txt_path}"
    mp3_path = r"{mp3_path}"
    voice = "{voice}"

    with open(txt_path, "r", encoding="utf-8") as f:
        text = f.read().strip()
    if not text:
        return

    import edge_tts
    comm = edge_tts.Communicate(text, voice)
    await comm.save(mp3_path)

    import pygame
    pygame.mixer.init()
    pygame.mixer.music.load(mp3_path)
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        pygame.time.wait(100)
    pygame.mixer.music.stop()
    pygame.mixer.quit()

asyncio.run(main())
'''


def speak(
    text: str,
    voice: str = "zh-TW-HsiaoChenNeural",
    backend: Optional[str] = None,
    piper_voice: Optional[str] = None,
):
    """
    Speak text using configured or requested backend.
    backend: 'piper' | 'edge' | None (default: ~/.dolores/config.json or piper)
    """
    cfg = load_config()
    be = (backend or cfg.get("tts_backend") or DEFAULT_TTS_BACKEND).lower()
    if be not in ("edge", "piper"):
        be = DEFAULT_TTS_BACKEND
    if be == "piper":
        pid = piper_voice or cfg.get("piper_voice") or default_piper_voice()
        if speak_piper(text, voice_id=pid):
            return
        speak_edge(text, voice)
        return
    speak_edge(text, voice)
