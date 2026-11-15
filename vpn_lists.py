"""Local VPN / datacenter / Tor detection using free public IP lists.

No API, no sign-up, and visitor IPs never leave your server.
Lists are downloaded to LIST_DIR and refreshed every 24h in the background.
"""
import bisect
import ipaddress
import os
import threading
import time

import requests

LIST_DIR = os.environ.get("LIST_DIR", "iplists")
MAX_AGE = 24 * 3600  # re-download lists older than this

_BASE = "https://raw.githubusercontent.com/X4BNet/lists_vpn/main/output"
SOURCES = {
    "vpn": [f"{_BASE}/vpn/ipv4.txt", f"{_BASE}/vpn/ipv6.txt"],
    "datacenter": [f"{_BASE}/datacenter/ipv4.txt", f"{_BASE}/datacenter/ipv6.txt"],
    "tor": ["https://check.torproject.org/torbulkexitlist"],
}

_tables = None  # {name: {4: (starts, ends), 6: (starts, ends)}}
_started = False
_lock = threading.Lock()


def _download(url, path):
    """Download to a temp file then swap in. Returns True on success."""
    try:
        r = requests.get(url, timeout=30)
        if r.status_code != 200 or not r.text.strip():
            return False
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.write(r.text)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def _read_networks(path):
    nets = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                nets.append(ipaddress.ip_network(line, strict=False))
            except ValueError:
                pass
    return nets


def _merge(ranges):
    ranges.sort()
    merged = []
    for start, end in ranges:
        if merged and start <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [m[0] for m in merged], [m[1] for m in merged]


def refresh():
    """Download stale lists (keeping old copies if a download fails) and rebuild lookups."""
    global _tables
    os.makedirs(LIST_DIR, exist_ok=True)
    tables = {}
    for name, urls in SOURCES.items():
        ranges = {4: [], 6: []}
        for i, url in enumerate(urls):
            path = os.path.join(LIST_DIR, f"{name}_{i}.txt")
            stale = not os.path.exists(path) or time.time() - os.path.getmtime(path) > MAX_AGE
            if stale:
                _download(url, path)
            if os.path.exists(path):
                for net in _read_networks(path):
                    ranges[net.version].append(
                        [int(net.network_address), int(net.broadcast_address)]
                    )
        tables[name] = {v: _merge(r) for v, r in ranges.items()}
    with _lock:
        _tables = tables


def _loop():
    while True:
        try:
            refresh()
        except Exception:
            pass
        time.sleep(3600)  # refresh() only re-downloads files older than MAX_AGE


def start():
    """Start the background loader once per process."""
    global _started
    if not _started:
        _started = True
        threading.Thread(target=_loop, daemon=True).start()


def lookup(ip):
    """Return {'flag': 1/0/None, 'reason': 'vpn,datacenter,...'}."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return {"flag": None, "reason": "invalid-ip"}
    if addr.is_private or addr.is_loopback or addr.is_reserved:
        return {"flag": None, "reason": "private-ip"}

    with _lock:
        tables = _tables
    if tables is None:
        return {"flag": None, "reason": "lists-loading"}

    n = int(addr)
    reasons = []
    for name, by_version in tables.items():
        starts, ends = by_version[addr.version]
        i = bisect.bisect_right(starts, n) - 1
        if i >= 0 and n <= ends[i]:
            reasons.append(name)
    return {"flag": 1 if reasons else 0, "reason": ",".join(reasons)}
