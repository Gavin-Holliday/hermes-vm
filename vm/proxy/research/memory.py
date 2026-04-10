import asyncio
import logging
from enum import Enum

import httpx
import psutil

log = logging.getLogger("hermes.research.memory")


class MemoryState(Enum):
    NORMAL = "normal"
    PRESSURE = "pressure"
    CRITICAL = "critical"


class MemoryGuard:
    def __init__(self, threshold_pct: int = 20, critical_pct: int = 10,
                 ollama_host: str = "http://localhost:11434"):
        self._threshold = threshold_pct
        self._critical = critical_pct
        self._ollama_host = ollama_host
        self._research_active: bool = False
        self._research_models: set = set()
        self._state: MemoryState = MemoryState.NORMAL
        self._monitor_task = None

    def start(self) -> None:
        self._monitor_task = asyncio.ensure_future(self._monitor_loop())

    def stop(self) -> None:
        if self._monitor_task:
            self._monitor_task.cancel()

    def set_research_active(self, models: set) -> None:
        self._research_active = True
        self._research_models = models

    def set_research_inactive(self) -> None:
        self._research_active = False
        self._research_models = set()

    def state(self) -> MemoryState:
        return self._state

    def should_defer_chat(self) -> bool:
        return self._research_active and self._state in (MemoryState.PRESSURE, MemoryState.CRITICAL)

    def should_pause_research(self) -> bool:
        return self._state == MemoryState.CRITICAL

    def _update_state(self) -> None:
        vm = psutil.virtual_memory()
        available_pct = 100.0 - vm.percent
        if available_pct < self._critical:
            self._state = MemoryState.CRITICAL
        elif available_pct < self._threshold:
            self._state = MemoryState.PRESSURE
        else:
            self._state = MemoryState.NORMAL

    async def _monitor_loop(self) -> None:
        while True:
            try:
                prev = self._state
                self._update_state()
                if self._state == MemoryState.PRESSURE and self._research_active:
                    await self._evict_non_research_models()
                if self._state != prev:
                    log.info("Memory state: %s → %s", prev.value, self._state.value)
            except Exception as e:
                log.warning("Memory monitor error: %s", e)
            await asyncio.sleep(30)

    async def _evict_non_research_models(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._ollama_host}/api/ps")
                if resp.status_code != 200:
                    return
                loaded = [m["name"] for m in resp.json().get("models", [])]
                for model in loaded:
                    if model not in self._research_models:
                        await client.post(
                            f"{self._ollama_host}/api/chat",
                            json={"model": model, "messages": [], "keep_alive": 0},
                        )
                        log.info("Evicted model from memory: %s", model)
        except Exception as e:
            log.warning("Model eviction failed: %s", e)
