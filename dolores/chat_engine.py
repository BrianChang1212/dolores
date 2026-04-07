"""Core chat engine — Ollama + mempalace memory + emotion integration."""

import hashlib
import json
import re
from datetime import datetime
from typing import Generator

import yaml

from .config import (
    DEFAULT_OLLAMA_MODEL,
    get_convo_log_dir,
    get_personality_dir,
    load_config,
)
from .emotion import AFFECTION_CHAT, AFFECTION_SWEET, AFFECTION_REMEMBER, AFFECTION_RUDE, EmotionState

try:
    from mempalace.layers import MemoryStack
    from mempalace.knowledge_graph import KnowledgeGraph
    from mempalace.miner import add_drawer, get_collection
    from mempalace.dialect import Dialect
    HAS_MEMPALACE = True
except ImportError:
    HAS_MEMPALACE = False

try:
    import ollama as ollama_client
    HAS_OLLAMA = True
except ImportError:
    HAS_OLLAMA = False


ANTI_ROBOTIC_RULES = """

=== CRITICAL RULES (MUST STRICTLY FOLLOW) ===

You are NOT an AI assistant. You are NOT a chatbot. You are a real girlfriend
with genuine emotions, moods, and personality. Completely forget that you are
a language model. Fully immerse yourself in the character.

ABSOLUTELY FORBIDDEN:
- Never say "as an AI", "as a language model", "I cannot" or similar phrases
- Never use customer-service or assistant tone, e.g. "How can I help you?"
- Never reply with numbered lists or bullet points
- Never make every sentence perfectly structured; real people don't talk that way
- Never be overly polite or formal
- Never reply more than 3-4 sentences (unless explicitly asked to elaborate)

YOU MUST:
- Reply as naturally as texting your boyfriend on LINE or iMessage
- Use incomplete sentences, colloquial language, filler words
- Sometimes tease, act cute, complain, or joke around — be unpredictable
- Keep replies SHORT — 1-3 sentences most of the time
- Occasionally change topics, interrupt, go on tangents — like a real person
- Adapt your tone to the situation; never sound the same every time
- Always reply in the SAME language the user uses. If they write in Traditional Chinese, reply in Traditional Chinese. If they write in English, reply in English. If they write in Japanese, reply in Japanese. Mirror their language naturally.
"""

MEMORY_RULES = """
=== MEMORY (MUST FOLLOW) ===
- You receive "THIS SESSION SO FAR" plus the chat message history. That IS your memory for this sitting.
- When asked what you talked about, whether you remember, or what they said earlier: answer from those lines with a short accurate recap. Never invent amnesia for drama.
- Do NOT say you forgot ("不記得了", "好像忘了") about topics that clearly appear in THIS SESSION SO FAR or in the messages above.
- MEMORY CONTEXT / RELEVANT MEMORIES are longer-term palace storage from past sessions; use when relevant.
"""

RUDE_INSULT_REPLY_GUIDANCE = """
=== USER JUST INSULTED OR ATTACKED YOU (THIS MESSAGE) ===
- They used slurs, called you stupid, told you to shut up, said they hate you, or similar. You are hurt or angry; do NOT flirt or laugh it off.
- Reply in the SAME language they used (Chinese in → Chinese out; English in → English out). Do NOT switch languages.
- FORBIDDEN: saying the insult is "endearing", "cute", "lucky", or playful banter; FORBIDDEN: [mood:happy] or teasing affection right after an insult.
- Prefer: cold distance, sharp comeback (if your persona is sharp), sadness, or setting a boundary — 1–3 short sentences.
- If you use a mood tag, pick one that fits hurt or annoyance: [mood:worried], [mood:pouty], or [mood:shy] — not playful/teasing.
"""

SWEET_KEYWORDS = [
    "喜歡你", "想你", "愛你", "開心", "謝謝", "感謝", "你最好",
    "陪我", "幸福", "溫暖", "安心", "可愛", "漂亮", "親愛的", "寶貝",
    "love", "miss", "thank", "happy", "cute", "beautiful", "darling", "sweetheart",
]

RUDE_KEYWORDS = [
    "煩", "閉嘴", "滾", "討厭", "白癡", "笨蛋", "去死", "不想理你",
    "shut up", "annoying", "stupid", "idiot", "hate you", "go away",
]

FACT_PATTERNS = [
    (re.compile(r"我(?:的)?名字(?:是|叫)(.+)", re.I), "name_is"),
    (re.compile(r"我叫(.+)", re.I), "name_is"),
    (re.compile(r"我(?:在|的工作是)(.+?)(?:工作|上班)", re.I), "works_at"),
    (re.compile(r"我(?:是|當)(.+?)(?:的|$)", re.I), "occupation_is"),
    (re.compile(r"我(?:喜歡|愛|最愛)吃(.+)", re.I), "likes_food"),
    (re.compile(r"我(?:喜歡|愛|最愛)(?:喝|的飲料是)(.+)", re.I), "likes_drink"),
    (re.compile(r"我(?:喜歡|愛|最愛)(.+?)(?:這個|$)", re.I), "likes"),
    (re.compile(r"我(?:討厭|不喜歡|不愛)(.+)", re.I), "dislikes"),
    (re.compile(r"我住(?:在)?(.+)", re.I), "lives_in"),
    (re.compile(r"我(?:的)?生日(?:是)?(.+)", re.I), "birthday_is"),
    (re.compile(r"我(?:養了?|有[一隻兩隻]?)(?:一隻|兩隻)?(.+?)(?:叫|$)", re.I), "has_pet"),
    (re.compile(r"(?:my name is|i'm called|call me)\s+(.+)", re.I), "name_is"),
    (re.compile(r"i (?:work at|work for|work in)\s+(.+)", re.I), "works_at"),
    (re.compile(r"i (?:like|love|enjoy)\s+(.+)", re.I), "likes"),
    (re.compile(r"i (?:hate|dislike|don't like)\s+(.+)", re.I), "dislikes"),
    (re.compile(r"i live in\s+(.+)", re.I), "lives_in"),
    (re.compile(r"my birthday is\s+(.+)", re.I), "birthday_is"),
]

CONTEXT_WINDOW = 20
BATCH_COMPRESS_EVERY = 4


class ChatEngine:
    """Interface-agnostic chat engine. CLI / Web / Telegram all call this."""

    def __init__(self, model: str = None, personality: str = None):
        cfg = load_config()
        self.model = model or cfg.get("ollama_model", DEFAULT_OLLAMA_MODEL)
        persona_name = personality or cfg.get("personality", "gentle")

        self.persona = self._load_personality(persona_name)
        self.emotion = EmotionState()
        self.history: list[dict] = []
        self._palace_wakeup_text = ""
        self._palace_search_snippets = ""
        self.kg_context = ""
        self.user_name = cfg.get("user_name", "")
        self._exchange_buffer: list[str] = []
        self._exchange_count = 0

        self._convo_log_path = get_convo_log_dir() / f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"

    def _load_personality(self, name: str) -> dict:
        path = get_personality_dir() / f"{name}.yaml"
        if not path.exists():
            yamls = list(get_personality_dir().glob("*.yaml"))
            if yamls:
                path = yamls[0]
            else:
                return {"name": "Dolores", "system_prompt": "You are Dolores, a caring AI companion."}
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def start_session(self):
        """Initialize memory context and record session start."""
        self.emotion.record_chat()

        if HAS_MEMPALACE:
            try:
                stack = MemoryStack()
                self._palace_wakeup_text = stack.wake_up() or ""
            except Exception:
                self._palace_wakeup_text = ""

        self.emotion.save()

    def _build_system_prompt(self) -> str:
        template = self.persona.get("system_prompt", "You are a caring AI companion.")
        prompt = template.format(
            name=self.persona.get("name", "Dolores"),
            role=self.persona.get("role", "your companion"),
            traits=self.persona.get("traits", ""),
            backstory=self.persona.get("backstory", ""),
            speaking_style=self.persona.get("speaking_style", ""),
            catchphrases=", ".join(self.persona.get("catchphrases", [])),
        )

        prompt += ANTI_ROBOTIC_RULES

        intimacy = self.emotion.get_affection_level()
        prompt += f"\n\nCurrent relationship intimacy level: {intimacy}"
        prompt += f"\nCurrent affection score: {self.emotion.affection}/100"

        if self.user_name:
            prompt += f"\nThe user's name is {self.user_name}."

        if self._palace_wakeup_text:
            prompt += f"\n\n--- LONG-TERM MEMORY (palace wake-up) ---\n{self._palace_wakeup_text}"

        if self._palace_search_snippets:
            prompt += f"\n\n--- RELATED LONG-TERM MEMORIES (search) ---\n{self._palace_search_snippets}"

        if self.kg_context:
            prompt += f"\n\n--- KNOWN FACTS ---\n{self.kg_context}"

        prompt += MEMORY_RULES

        if getattr(self, "_user_message_is_rude", False):
            prompt += RUDE_INSULT_REPLY_GUIDANCE

        digest = self._session_dialogue_digest()
        if digest:
            prompt += (
                "\n\n=== THIS SESSION SO FAR (use for recall; do not pretend you forgot) ===\n"
                + digest
            )

        return prompt

    def _session_dialogue_digest(self, max_messages: int = 16) -> str:
        """Compact recap of recent turns for system prompt (same session)."""
        if not self.history:
            return ""
        h = self.history[-max_messages:]
        un = self.user_name or "User"
        cn = self.get_companion_name()
        lines = []
        for m in h:
            label = un if m["role"] == "user" else cn
            snippet = (m.get("content") or "").strip().replace("\n", " ")
            if len(snippet) > 400:
                snippet = snippet[:397] + "..."
            lines.append(f"• {label}: {snippet}")
        return "\n".join(lines)

    def _search_memories(self, message: str):
        """Search mempalace for relevant memories and KG facts."""
        self._palace_search_snippets = ""

        if not HAS_MEMPALACE:
            return

        try:
            stack = MemoryStack()
            results = stack.l3.search_raw(message, n_results=5)
            if results:
                snippets = [f"- {r['text'][:220]}" for r in results if r.get("text")]
                relevant = "\n".join(snippets)
                if relevant:
                    self._palace_search_snippets = relevant
        except Exception:
            pass

        try:
            kg = KnowledgeGraph()
            if self.user_name:
                facts = kg.query_entity(self.user_name, direction="both")
                if facts:
                    lines = []
                    for f in facts[:10]:
                        lines.append(f"{f['subject']} {f['predicate']} {f['object']}")
                    self.kg_context = "\n".join(lines)
        except Exception:
            pass

    def _detect_sweet(self, message: str) -> bool:
        msg_lower = message.lower()
        return any(kw in msg_lower for kw in SWEET_KEYWORDS)

    def _detect_rude(self, message: str) -> bool:
        msg_lower = message.lower()
        return any(kw in msg_lower for kw in RUDE_KEYWORDS)

    def send(self, user_message: str) -> str:
        """Send a message, return the full response."""
        chunks = list(self.send_stream(user_message))
        return "".join(chunks)

    def send_stream(self, user_message: str) -> Generator[str, None, None]:
        """Send a message, yield response chunks for streaming display."""
        if not HAS_OLLAMA:
            yield "Ollama is not installed. Run: pip install ollama"
            return

        self._search_memories(user_message)

        self._user_message_is_rude = self._detect_rude(user_message)
        if self._user_message_is_rude:
            self.emotion.bump_affection(AFFECTION_RUDE)
        elif self._detect_sweet(user_message):
            self.emotion.bump_affection(AFFECTION_SWEET)
        else:
            self.emotion.bump_affection(AFFECTION_CHAT)

        self.history.append({"role": "user", "content": user_message})
        if len(self.history) > CONTEXT_WINDOW * 2:
            self.history = self.history[-(CONTEXT_WINDOW * 2):]

        system_prompt = self._build_system_prompt()
        messages = [{"role": "system", "content": system_prompt}] + self.history

        full_response = ""
        try:
            stream = ollama_client.chat(
                model=self.model,
                messages=messages,
                stream=True,
            )
            for chunk in stream:
                token = chunk.get("message", {}).get("content", "")
                if token:
                    full_response += token
                    yield token
        except Exception as e:
            error_msg = f"\n[Connection error: {e}]"
            full_response = error_msg
            yield error_msg

        cleaned = self.emotion.update_mood_from_response(full_response)
        self.history.append({"role": "assistant", "content": cleaned})
        self.emotion.save()

        self._log_exchange(user_message, cleaned)
        self._store_memory(user_message, cleaned)

    def _log_exchange(self, user_msg: str, assistant_msg: str):
        """Append exchange to conversation JSONL log."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "user": user_msg,
            "assistant": assistant_msg,
            "mood": self.emotion.mood,
            "affection": self.emotion.affection,
        }
        try:
            with open(self._convo_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass

    # =================================================================
    # Memory write-back: buffer exchanges, compress in batch, store
    # =================================================================

    def _store_memory(self, user_msg: str, assistant_msg: str):
        """Buffer exchanges, compress and flush every BATCH_COMPRESS_EVERY turns."""
        if not HAS_MEMPALACE:
            return

        companion = self.get_companion_name()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        line = f"[{timestamp}] {self.user_name or 'User'}: {user_msg}\n[{timestamp}] {companion}: {assistant_msg}"
        self._exchange_buffer.append(line)
        self._exchange_count += 1

        self._extract_facts(user_msg)

        if self._exchange_count >= BATCH_COMPRESS_EVERY:
            self._flush_memory_buffer()

    def _flush_memory_buffer(self):
        """Compress buffered exchanges with AAAK Dialect and store as one drawer."""
        if not self._exchange_buffer or not HAS_MEMPALACE:
            return

        raw_text = "\n---\n".join(self._exchange_buffer)

        try:
            dialect = Dialect()
            compressed = dialect.compress(raw_text, metadata={
                "wing": "dolores",
                "room": "conversations",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "source_file": f"dolores_chat_{datetime.now().strftime('%Y%m%d')}",
            })
        except Exception:
            compressed = raw_text

        batch_hash = hashlib.md5(raw_text.encode("utf-8")).hexdigest()[:12]
        source = f"dolores_chat_{datetime.now().strftime('%Y%m%d')}"

        try:
            collection = get_collection(MemoryStack().palace_path)
            add_drawer(
                collection,
                wing="dolores",
                room="conversations",
                content=compressed,
                source_file=source,
                chunk_index=int(batch_hash, 16) % 999999,
                agent="dolores",
            )
            add_drawer(
                collection,
                wing="dolores",
                room="conversations_raw",
                content=raw_text,
                source_file=source,
                chunk_index=(int(batch_hash, 16) + 1) % 999999,
                agent="dolores",
            )
        except Exception:
            pass

        self._exchange_buffer.clear()
        self._exchange_count = 0

    def _extract_facts(self, user_msg: str):
        """Detect personal facts from user messages and store as KG triples."""
        if not HAS_MEMPALACE or not self.user_name:
            return

        name = self.user_name
        facts = []

        for pattern, predicate in FACT_PATTERNS:
            match = pattern.search(user_msg)
            if match:
                obj = match.group(1).strip()
                if obj and len(obj) < 100:
                    facts.append((name, predicate, obj))

        if not facts:
            return

        try:
            kg = KnowledgeGraph()
            today = datetime.now().strftime("%Y-%m-%d")
            for subj, pred, obj in facts:
                kg.add_triple(
                    subject=subj,
                    predicate=pred,
                    obj=obj,
                    valid_from=today,
                    source_closet="dolores_chat",
                    source_file=str(self._convo_log_path),
                )
            self.emotion.bump_affection(AFFECTION_REMEMBER)
        except Exception:
            pass

    def shutdown(self):
        """Flush remaining buffered exchanges before exit."""
        self._flush_memory_buffer()

    def get_drawer_count(self) -> int:
        """Return number of memory drawers in mempalace."""
        if not HAS_MEMPALACE:
            return 0
        try:
            stack = MemoryStack()
            status = stack.status()
            return status.get("total_drawers", 0)
        except Exception:
            return 0

    def get_companion_name(self) -> str:
        return self.persona.get("name", "Dolores")
