"""Mood and affection tracking for Dolores companions."""

import json
import os
import re
from datetime import datetime

from .config import DEFAULT_STATE_PATH, _ensure_dir


MOODS = {
    "happy":   {"emoji": "\U0001f60a", "label": "Happy"},
    "tender":  {"emoji": "\U0001f970", "label": "Tender"},
    "worried": {"emoji": "\U0001f61f", "label": "Worried"},
    "pouty":   {"emoji": "\U0001f624", "label": "Pouty"},
    "shy":     {"emoji": "\U0001f97a", "label": "Shy"},
}

DEFAULT_MOOD = "happy"
DEFAULT_AFFECTION = 50
MAX_AFFECTION = 100
MIN_AFFECTION = 0

AFFECTION_CHAT = 2
AFFECTION_SWEET = 5
AFFECTION_REMEMBER = 3
AFFECTION_RUDE = -3
AFFECTION_DECAY_PER_DAY = -1

MOOD_TAG_RE = re.compile(r"\[mood:(\w+)\]", re.IGNORECASE)


class EmotionState:
    """Track companion mood and affection, persisted to state.json."""

    def __init__(self):
        self.mood = DEFAULT_MOOD
        self.affection = DEFAULT_AFFECTION
        self.total_conversations = 0
        self.last_chat = None
        self.first_met = None
        self._load()

    def _load(self):
        if not os.path.exists(DEFAULT_STATE_PATH):
            return
        with open(DEFAULT_STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.mood = data.get("mood", DEFAULT_MOOD)
        self.affection = data.get("affection", DEFAULT_AFFECTION)
        self.total_conversations = data.get("total_conversations", 0)
        self.last_chat = data.get("last_chat")
        self.first_met = data.get("first_met")
        self._apply_decay()

    def _apply_decay(self):
        """Reduce affection for days without chatting."""
        if not self.last_chat:
            return
        try:
            last = datetime.fromisoformat(self.last_chat)
        except (ValueError, TypeError):
            return
        days_gone = (datetime.now() - last).days
        if days_gone > 0:
            penalty = days_gone * AFFECTION_DECAY_PER_DAY
            self.affection = max(MIN_AFFECTION, self.affection + penalty)

    def save(self):
        _ensure_dir(DEFAULT_STATE_PATH)
        data = {
            "mood": self.mood,
            "affection": self.affection,
            "total_conversations": self.total_conversations,
            "last_chat": self.last_chat,
            "first_met": self.first_met,
        }
        with open(DEFAULT_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def bump_affection(self, delta: int):
        self.affection = max(MIN_AFFECTION, min(MAX_AFFECTION, self.affection + delta))

    def record_chat(self):
        """Call once per session start."""
        self.total_conversations += 1
        self.last_chat = datetime.now().isoformat()
        if not self.first_met:
            self.first_met = self.last_chat

    def update_mood_from_response(self, response_text: str) -> str:
        """Extract [mood:xxx] tag from LLM response, update state, return cleaned text."""
        match = MOOD_TAG_RE.search(response_text)
        if match:
            tag = match.group(1).lower()
            if tag in MOODS:
                self.mood = tag
            return MOOD_TAG_RE.sub("", response_text).strip()
        return response_text

    def get_mood_display(self) -> str:
        info = MOODS.get(self.mood, MOODS[DEFAULT_MOOD])
        return f"{info['emoji']} {info['label']}"

    def get_affection_bar(self, width: int = 10) -> str:
        filled = round(self.affection / MAX_AFFECTION * width)
        empty = width - filled
        pct = self.affection
        return f"{'█' * filled}{'░' * empty} {pct}%"

    def get_affection_level(self) -> str:
        """Return a human-readable intimacy level for prompt injection."""
        a = self.affection
        if a <= 20:
            return "polite but distant"
        if a <= 40:
            return "friendly, occasionally shy"
        if a <= 60:
            return "naturally close, sometimes sweet"
        if a <= 80:
            return "very intimate, proactively caring"
        return "deeply trusting, shares innermost feelings"
