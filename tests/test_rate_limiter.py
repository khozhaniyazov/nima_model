"""Rate limiter behavior checks."""

from algorithms.rate_limiter import SlidingWindowRateLimiter


def test_rate_limiter_allows_then_blocks_then_recovers():
    now = [100.0]
    limiter = SlidingWindowRateLimiter(
        enabled=True,
        max_requests=2,
        window_seconds=10,
        clock=lambda: now[0],
    )

    assert limiter.check("client-a") == (True, 0)
    assert limiter.check("client-a") == (True, 0)
    allowed, retry_after = limiter.check("client-a")
    assert allowed is False
    assert retry_after > 0

    now[0] = 111.0
    assert limiter.check("client-a") == (True, 0)
    print("[OK] rate limiter — blocks within window and recovers after expiry")


def test_rate_limiter_disabled_always_allows():
    limiter = SlidingWindowRateLimiter(
        enabled=False,
        max_requests=1,
        window_seconds=60,
    )

    assert limiter.check("client-a") == (True, 0)
    assert limiter.check("client-a") == (True, 0)
    print("[OK] rate limiter — disabled mode allows requests")


if __name__ == "__main__":
    test_rate_limiter_allows_then_blocks_then_recovers()
    test_rate_limiter_disabled_always_allows()
    print("\nALL RATE LIMITER CHECKS PASSED")
