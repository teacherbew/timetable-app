from fastapi import HTTPException, Request

from app.redis_client import redis_client

RATE_LIMIT_MAX_REQUESTS = 10
RATE_LIMIT_WINDOW_SECONDS = 60


def rate_limit(request: Request):
    """
    Simple fixed-window rate limiter keyed by client IP.
    If Redis is unreachable, fail open (don't block requests) rather than
    take down the whole endpoint — this matches how caching failures are
    already handled elsewhere in this app.
    """
    client_ip = request.client.host if request.client else "unknown"
    key = f"rate_limit:{client_ip}:{request.scope['path']}"

    try:
        requests = redis_client.incr(key)
        if requests == 1:
            redis_client.expire(key, RATE_LIMIT_WINDOW_SECONDS)
    except Exception:
        return

    if requests > RATE_LIMIT_MAX_REQUESTS:
        raise HTTPException(
            status_code=429,
            detail=f"Too many requests. Please wait {RATE_LIMIT_WINDOW_SECONDS} seconds.",
        )
