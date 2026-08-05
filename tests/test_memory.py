"""Runnable with: python tests/test_memory.py  (no external deps needed)."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.conversation import ConversationMemory
from memory.second_brain import SecondBrain


def test_conversation_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        mem = ConversationMemory(d)
        mem.add("user", "hello")
        mem.add("assistant", "hi there")
        recent = mem.recent(10)
        assert recent == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        mem.close()


def test_second_brain_recall():
    with tempfile.TemporaryDirectory() as d:
        sb = SecondBrain(d)
        sb.remember("My wifi password is banana123", tags="home")
        sb.remember("The gym opens at 6am on weekdays", tags="routine")
        hit = sb.recall("wifi password")
        assert "banana123" in hit
        miss = sb.recall("dragon spaceship")
        assert "match" in miss.lower() or "empty" in miss.lower()
        sb.close()


if __name__ == "__main__":
    test_conversation_roundtrip()
    test_second_brain_recall()
    print("All memory tests passed.")
