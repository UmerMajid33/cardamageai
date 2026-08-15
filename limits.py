"""Protection for a public deployment.

Once this is on the open internet the Groq key sits behind an unauthenticated
endpoint, and the free tier is exhausted by a handful of requests. Two layers:

- a per-IP limit, which stops one person hammering it
- a global limit, which is what actually protects the quota, because an
  attacker with a pool of addresses walks straight past a per-IP rule

Counters live in memory, so run a single worker. That is the right shape here
anyway: Groq's per-minute budget means concurrent requests would only queue up
behind each other and fail.
"""

import hmac
import os
import time
from collections import defaultdict, deque
from threading import Lock

WINDOW = 3600

PER_IP_PER_HOUR = int(os.environ.get("DAMAGESCAN_RATE_PER_IP", "12"))
GLOBAL_PER_HOUR = int(os.environ.get("DAMAGESCAN_RATE_GLOBAL", "60"))

# When set, callers must supply this before an assessment runs. Unset means
# open - fine locally, not fine on a public URL.
ACCESS_CODE = os.environ.get("DAMAGESCAN_ACCESS_CODE", "").strip()

_lock = Lock()
_by_ip = defaultdict(deque)
_global = deque()


class RateLimited(Exception):
    pass


class AccessDenied(Exception):
    pass


def client_ip(request):
    """Real client address behind Render's proxy."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _prune(queue, now):
    while queue and now - queue[0] > WINDOW:
        queue.popleft()


def _minutes_until_free(queue, now):
    return max(1, int((WINDOW - (now - queue[0])) / 60) + 1)


def check_access(supplied):
    """Constant-time comparison, so the code cannot be guessed by timing."""
    if not ACCESS_CODE:
        return
    if not hmac.compare_digest((supplied or "").strip(), ACCESS_CODE):
        raise AccessDenied("Wrong access code.")


def check_rate(ip):
    now = time.time()
    with _lock:
        _prune(_global, now)
        if len(_global) >= GLOBAL_PER_HOUR:
            raise RateLimited(
                f"This service is busy - it allows {GLOBAL_PER_HOUR} assessments "
                f"an hour in total. Try again in about "
                f"{_minutes_until_free(_global, now)} minutes."
            )

        mine = _by_ip[ip]
        _prune(mine, now)
        if len(mine) >= PER_IP_PER_HOUR:
            raise RateLimited(
                f"You have used your {PER_IP_PER_HOUR} assessments for this hour. "
                f"Try again in about {_minutes_until_free(mine, now)} minutes."
            )

        mine.append(now)
        _global.append(now)

        # Stop the IP table growing without bound on a long-lived process.
        if len(_by_ip) > 4096:
            for key in [k for k, q in _by_ip.items() if not q]:
                del _by_ip[key]


def status():
    now = time.time()
    with _lock:
        _prune(_global, now)
        return {
            "access_code_required": bool(ACCESS_CODE),
            "per_ip_per_hour": PER_IP_PER_HOUR,
            "global_per_hour": GLOBAL_PER_HOUR,
            "used_this_hour": len(_global),
        }
