import time
from proxy.rate_limit import TokenBucket


def test_allows_requests_within_burst():
    bucket = TokenBucket(burst=5, per_minute=60)
    for _ in range(5):
        assert bucket.consume() is True


def test_blocks_when_burst_exhausted():
    bucket = TokenBucket(burst=3, per_minute=60)
    bucket.consume()
    bucket.consume()
    bucket.consume()
    assert bucket.consume() is False


def test_refills_over_time():
    bucket = TokenBucket(burst=1, per_minute=60)
    assert bucket.consume() is True   # uses the 1 token
    assert bucket.consume() is False  # empty
    time.sleep(1.1)                   # 60/min = 1/sec, wait 1.1 sec
    assert bucket.consume() is True   # refilled


def test_does_not_exceed_burst_on_refill():
    bucket = TokenBucket(burst=3, per_minute=600)
    time.sleep(0.5)
    # Even after waiting, tokens should not exceed burst
    for _ in range(3):
        assert bucket.consume() is True
    assert bucket.consume() is False
