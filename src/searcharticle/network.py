"""
Network layer: HTTP requests, retry with backoff and connectivity
diagnostics.
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from .config import SessionState

#: Endpoints probed by the network diagnostics and their display labels.
_DIAG_ENDPOINTS: dict[str, tuple[str, str]] = {
    "internet": ("https://www.google.com", "Internet"),
    "doi": ("https://doi.org/10.1000/xyz123", "DOI resolver"),
    "ncbi": ("https://eutils.ncbi.nlm.nih.gov/", "NCBI / PMC"),
    "unpaywall": ("https://api.unpaywall.org/", "Unpaywall"),
}

#: Service used to determine the machine's public IP.
_PUBLIC_IP_URL = "https://api.ipify.org"

#: Key and label of the institutional-access indicator.
_DIAG_PROXY_KEY = "proxy"
_DIAG_PROXY_LABEL = "Institutional proxy"

#: User-Agent header sent with every request (full browser profile:
#: some publishers block truncated or "python-requests" User-Agents).
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


# ─────────────────────────────────────────────
#  HTTP REQUESTS
# ─────────────────────────────────────────────


def make_request(url: str, **kw) -> requests.Response:
    """
    Perform a GET request with default browser headers
    (some publishers reject clients that announce themselves as bots).

    Args:
        url: URL to fetch.
        **kw: Arguments forwarded to :func:`requests.get`.

    Returns:
        The HTTP response.
    """
    kw.setdefault("headers", {})
    kw["headers"].setdefault("User-Agent", _USER_AGENT)
    kw["headers"].setdefault(
        "Accept",
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "application/pdf;q=0.8,*/*;q=0.7",
    )
    kw["headers"].setdefault("Accept-Language", "en-US,en;q=0.9,fr;q=0.8")
    return requests.get(url, **kw)


def request_with_retry(
    request_fn,
    max_attempts: int = 3,
    base_delay: float = 2.0,
) -> tuple[requests.Response | None, str | None]:
    """
    Run ``request_fn()`` with automatic retry and exponential backoff.

    Distinguishes the cases:
      - Timeout / connection error → retry with growing delay (2s, 4s…).
      - HTTP 429 (rate-limit) → retry with an extended delay.
      - Other exception → no retry, the exception becomes a message.

    Args:
        request_fn: Zero-argument function returning an HTTP response.
        max_attempts: Maximum number of attempts.
        base_delay: Base delay in seconds (multiplied by the attempt number).

    Returns:
        Tuple ``(response, failure_reason)``: on success the reason is
        ``None``; otherwise the response is ``None`` and the reason
        describes the failure in plain language.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            r = request_fn()
            if r.status_code == 429:
                # Rate-limit: wait longer before retrying
                delay = base_delay * 3 * attempt
                if attempt < max_attempts:
                    time.sleep(delay)
                    continue
                return None, f"rate-limit (429) after {attempt} attempt(s)"
            return r, None

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            msg = str(e)
            # Human-readable diagnosis depending on the error type
            if "Read timed out" in msg or "Timeout" in msg:
                reason = f"network timeout (attempt {attempt}/{max_attempts})"
            elif "ConnectionPool" in msg or "Connection" in msg:
                reason = f"connection failed (attempt {attempt}/{max_attempts})"
            else:
                reason = f"network error: {msg[:60]}"

            if attempt < max_attempts:
                time.sleep(base_delay * attempt)  # 2s, 4s, …
                continue
            return None, reason

        except Exception as e:
            return None, str(e)[:80]

    return None, "failed after all attempts"


# ─────────────────────────────────────────────
#  NETWORK DIAGNOSTICS
# ─────────────────────────────────────────────


def _test_endpoint(key: str, url: str, timeout: int = 6) -> tuple[str, bool]:
    """Probe an endpoint; return ``(key, reachable)``."""
    try:
        r = make_request(
            url,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0"},
            allow_redirects=True,
        )
        # doi.org returns 404 for a fake DOI, but the connection succeeded
        return key, r.status_code < 500
    except Exception:
        return key, False


def check_institutional_proxy(ip_prefix: str, timeout: int = 8) -> tuple[str, bool]:
    """
    Check whether the machine is on the institution's network (campus or VPN).

    Fetch the machine's public IP and check that it starts with the
    configured institutional IP prefix (e.g. ``"132.204."``). It is this
    institutional IP that unlocks subscription articles on publisher
    sites.

    Args:
        ip_prefix: Public IP prefix of the institution.
        timeout: Timeout in seconds.

    Returns:
        Tuple ``("proxy", True/False)``: ``True`` if the public IP
        starts with ``ip_prefix``, ``False`` otherwise (or if the IP
        could not be determined).
    """
    try:
        r = make_request(_PUBLIC_IP_URL, timeout=timeout)
        ip = r.text.strip()
        return _DIAG_PROXY_KEY, ip.startswith(ip_prefix)
    except Exception:
        return _DIAG_PROXY_KEY, False


def diagnose_network(state: SessionState, callback=None) -> dict[str, bool | None]:
    """
    Probe connectivity in parallel and update ``state.diag``:
    Internet, institutional proxy, DOI, NCBI and Unpaywall.

    The proxy check only runs when an institutional IP prefix is
    configured (``state.config.institution_ip_prefix``); otherwise
    ``state.diag["proxy"]`` stays ``None`` (not tested) and no public-IP
    lookup is performed.

    Args:
        state: Session state to update.
        callback: Optional ``callback(key, ok)`` function called as soon
            as a result arrives (call it via ``.after()`` on the GUI side
            to stay thread-safe).

    Returns:
        The updated diagnostics dictionary.
    """
    ip_prefix = state.config.institution_ip_prefix.strip()
    with ThreadPoolExecutor(max_workers=5) as ex:
        futures = {
            ex.submit(_test_endpoint, key, url): key
            for key, (url, _) in _DIAG_ENDPOINTS.items()
        }
        if ip_prefix:
            futures[ex.submit(check_institutional_proxy, ip_prefix)] = _DIAG_PROXY_KEY
        for f in as_completed(futures):
            key, ok = f.result()
            state.diag[key] = ok
            if callback:
                callback(key, ok)
    return state.diag


def diagnostic_labels() -> dict[str, str]:
    """
    Return the display labels of the diagnostics indicators,
    in display order (institutional proxy right after Internet).

    Returns:
        Dict ``{key: label}`` (e.g. ``{"internet": "Internet", …}``).
    """
    labels: dict[str, str] = {}
    for key, (_, label) in _DIAG_ENDPOINTS.items():
        labels[key] = label
        if key == "internet":
            labels[_DIAG_PROXY_KEY] = _DIAG_PROXY_LABEL
    return labels
