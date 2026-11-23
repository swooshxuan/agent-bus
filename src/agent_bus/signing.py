"""Task signing with a shared HMAC key.

The sender signs ``target/title/body/sender`` with a shared secret; workers
verify it before executing. This proves a task was produced by someone who
holds the key (integrity + authenticity). It does not distinguish *which*
holder — per-agent asymmetric identity is a later step.
"""

import hashlib
import hmac


def _payload(target, title, body, sender):
    return "\n".join([target or "", title or "", body or "",
                      sender or ""]).encode("utf-8")


def sign_task(key, target, title, body, sender):
    return hmac.new(key.encode("utf-8"),
                    _payload(target, title, body, sender),
                    hashlib.sha256).hexdigest()


def verify_task(key, task):
    """Return (ok, reason) for a task dict that may carry a "sig"."""
    signature = task.get("sig")
    if not signature:
        return False, "missing signature"
    expected = sign_task(key, task.get("target", ""), task.get("title", ""),
                         task.get("body", ""), task.get("sender", ""))
    if not hmac.compare_digest(str(signature), expected):
        return False, "invalid signature"
    return True, "ok"
