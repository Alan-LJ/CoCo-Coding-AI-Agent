from __future__ import annotations

import asyncio
from pathlib import Path

from coco_code.conversation import ChatMessage
from coco_code.llm import StreamEvent, StreamEventType
from coco_code.memory import MemoryAction, MemoryLevel, MemoryManager, MemoryStore, NoteType


class FakeProvider:
    name = "fake"
    model = "fake-model"
    protocol = "openai"

    def __init__(self, text: str) -> None:
        self.text = text
        self.tools_seen = []

    async def stream(self, messages, tools=None):
        self.tools_seen.append(tools)
        yield StreamEvent(type=StreamEventType.TEXT_DELTA, text=self.text)
        yield StreamEvent(type=StreamEventType.DONE)


def test_memory_store_create_update_delete(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path, MemoryLevel.PROJECT)
    create = MemoryAction(
        action="create",
        level=MemoryLevel.PROJECT,
        type=NoteType.PROJECT_KNOWLEDGE,
        title="API rules",
        slug="api_rules",
        content="Use typed configs.",
    )
    store.apply_actions([create])
    note = tmp_path / "project_knowledge_api_rules.md"
    assert note.exists()
    assert "type: project_knowledge" in note.read_text(encoding="utf-8")
    assert "API rules" in store.load_index()
    update = MemoryAction(
        action="update",
        level=MemoryLevel.PROJECT,
        filename=note.name,
        title="API rules",
        content="Use typed configs and tests.",
    )
    store.apply_actions([update])
    assert "tests" in note.read_text(encoding="utf-8")
    delete = MemoryAction(action="delete", level=MemoryLevel.PROJECT, filename=note.name)
    store.apply_actions([delete])
    assert not note.exists()
    assert note.name not in store.load_index()


def test_memory_manager_index_and_update(tmp_path: Path) -> None:
    async def run() -> None:
        provider = FakeProvider(
            '[{"action":"create","level":"project","type":"project_knowledge",'
            '"title":"Testing","slug":"testing","content":"Always test."}]'
        )
        manager = MemoryManager(tmp_path, provider=provider)
        await manager.update_async([ChatMessage(role="user", content="记住要测试")])
        assert provider.tools_seen == [None]
        assert (tmp_path / ".coco-code" / "memory" / "project_knowledge_testing.md").exists()
        index = manager.load_index_text()
        assert "项目级记忆" in index
        assert "Testing" in index

    asyncio.run(run())
