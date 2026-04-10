import pytest
from unittest.mock import patch, MagicMock
from proxy.research.memory import MemoryGuard, MemoryState


def _mock_vm(percent: float):
    m = MagicMock()
    m.percent = percent
    return m


def test_normal_state_plenty_of_ram():
    guard = MemoryGuard(threshold_pct=20, critical_pct=10)
    with patch("psutil.virtual_memory", return_value=_mock_vm(50.0)):
        guard._update_state()
    assert guard.state() == MemoryState.NORMAL


def test_pressure_state():
    guard = MemoryGuard(threshold_pct=20, critical_pct=10)
    with patch("psutil.virtual_memory", return_value=_mock_vm(85.0)):
        guard._update_state()
    assert guard.state() == MemoryState.PRESSURE


def test_critical_state():
    guard = MemoryGuard(threshold_pct=20, critical_pct=10)
    with patch("psutil.virtual_memory", return_value=_mock_vm(95.0)):
        guard._update_state()
    assert guard.state() == MemoryState.CRITICAL


def test_should_defer_chat_when_pressure_and_active():
    guard = MemoryGuard()
    guard.set_research_active({"gemma4:e4b", "gemma4:26b"})
    guard._state = MemoryState.PRESSURE
    assert guard.should_defer_chat() is True


def test_should_not_defer_chat_when_not_active():
    guard = MemoryGuard()
    guard._state = MemoryState.PRESSURE
    assert guard.should_defer_chat() is False


def test_should_pause_research_only_on_critical():
    guard = MemoryGuard()
    guard._state = MemoryState.PRESSURE
    assert guard.should_pause_research() is False
    guard._state = MemoryState.CRITICAL
    assert guard.should_pause_research() is True
