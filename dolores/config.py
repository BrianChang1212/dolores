"""Configuration management for Dolores."""

import json
import os
from pathlib import Path


DEFAULT_CONFIG_DIR = os.path.expanduser("~/.dolores")
DEFAULT_CONFIG_PATH = os.path.join(DEFAULT_CONFIG_DIR, "config.json")
DEFAULT_STATE_PATH = os.path.join(DEFAULT_CONFIG_DIR, "state.json")
DEFAULT_OLLAMA_MODEL = "gemma4:e4b"
DEFAULT_PERSONALITY = "gentle"
DEFAULT_TTS_BACKEND = "piper"
DEFAULT_PIPER_VOICE = "zh_CN-huayan-medium"


def _ensure_dir(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    """Load config from ~/.dolores/config.json, return defaults if missing."""
    if os.path.exists(DEFAULT_CONFIG_PATH):
        with open(DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(cfg: dict):
    """Persist config to ~/.dolores/config.json."""
    _ensure_dir(DEFAULT_CONFIG_PATH)
    with open(DEFAULT_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


def is_first_run() -> bool:
    return not os.path.exists(DEFAULT_CONFIG_PATH)


def get_personality_dir() -> Path:
    """Return the path to bundled personality YAML files."""
    return Path(__file__).parent / "personalities"


def get_project_root() -> Path:
    """Return the dolores project root (one level above the package)."""
    return Path(__file__).parent.parent


def get_personal_dir() -> Path:
    """Return the personal/ data directory."""
    cfg = load_config()
    custom = cfg.get("personal_data_path")
    if custom and os.path.isdir(custom):
        return Path(custom)
    return get_project_root() / "personal"


def get_convo_log_dir() -> Path:
    """Return directory for conversation JSONL logs."""
    d = Path(DEFAULT_CONFIG_DIR) / "conversations"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_piper_voices_dir() -> Path:
    """Directory for Piper ONNX models (~/.dolores/piper_voices/)."""
    d = Path(DEFAULT_CONFIG_DIR) / "piper_voices"
    d.mkdir(parents=True, exist_ok=True)
    return d
