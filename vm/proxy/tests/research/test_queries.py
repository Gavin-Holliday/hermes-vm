import pytest
from proxy.research.queries import QueryManager


@pytest.fixture
def qm():
    return QueryManager()


def test_expand_returns_multiple_queries(qm):
    queries = qm.expand("bitcoin ETF")
    assert len(queries) >= 6


def test_expand_no_duplicates(qm):
    queries = qm.expand("bitcoin ETF")
    assert len(queries) == len(set(queries))


def test_next_batch_returns_up_to_n(qm):
    qm.expand("test topic")
    batch = qm.next_batch(3)
    assert len(batch) <= 3


def test_next_batch_marks_used(qm):
    qm.expand("test topic")
    batch1 = qm.next_batch(3)
    batch2 = qm.next_batch(3)
    assert not any(q in batch1 for q in batch2)


def test_is_duplicate_exact(qm):
    qm.expand("bitcoin")
    qm.next_batch(20)  # mark all as used
    assert qm.is_duplicate("bitcoin") is True


def test_is_duplicate_similar(qm):
    qm._used.add("bitcoin ETF approval 2024")
    assert qm.is_duplicate("bitcoin ETF approval") is True


def test_is_duplicate_different(qm):
    qm._used.add("bitcoin ETF")
    assert qm.is_duplicate("ethereum staking rewards") is False


def test_cache_round_trip(qm):
    results = [{"title": "T", "url": "https://x.com"}]
    qm.cache_results("my query", results)
    assert qm.get_cached("my query") == results


def test_pending_count(qm):
    qm.expand("test topic")
    initial = qm.pending_count()
    qm.next_batch(3)
    assert qm.pending_count() == initial - 3


def test_add_from_gaps(qm):
    qm.expand("bitcoin")
    before = qm.pending_count()
    added = qm.add_from_gaps(["new gap query", "another gap"])
    assert len(added) == 2
    assert qm.pending_count() == before + 2
