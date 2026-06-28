"""Shared helpers: dependency-free config loading, HTTP, and small utilities.

The pipeline targets the Python standard library only, so this module includes a
minimal YAML reader sufficient for ``config.yaml`` (nested maps, inline ``[a, b]``
lists, ``- item`` lists, and scalars) and a small HTTP helper that accepts custom
headers (ESPN works anonymously; the NBL feed is referer-gated; stats.nba.com
needs a browser header bundle).
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


# --------------------------------------------------------------------------- #
# Minimal YAML
# --------------------------------------------------------------------------- #
def _coerce(scalar: str) -> Any:
    s = scalar.strip()
    if s == "" or s in ("~", "null", "None"):
        return None
    if (s[0] == s[-1]) and s[0] in ("'", '"') and len(s) >= 2:
        return s[1:-1]
    low = s.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _split_top(s: str) -> list[str]:
    """Split on commas not inside quotes/brackets."""
    out, depth, buf, quote = [], 0, "", None
    for ch in s:
        if quote:
            buf += ch
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            buf += ch
        elif ch in "[{":
            depth += 1
            buf += ch
        elif ch in "]}":
            depth -= 1
            buf += ch
        elif ch == "," and depth == 0:
            out.append(buf)
            buf = ""
        else:
            buf += ch
    if buf.strip():
        out.append(buf)
    return out


def _parse_inline_list(s: str) -> list:
    inner = s.strip()[1:-1].strip()
    if not inner:
        return []
    return [_coerce(p) for p in _split_top(inner)]


def _strip_comment(line: str) -> str:
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "#":
            return line[:i]
    return line


def load_yaml(text: str) -> Any:
    rows = []
    for raw in text.splitlines():
        line = _strip_comment(raw).rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        rows.append((indent, line.strip()))

    def parse_block(idx: int, indent: int):
        if rows[idx][1].startswith("- "):
            items = []
            while idx < len(rows) and rows[idx][0] == indent and rows[idx][1].startswith("- "):
                items.append(_coerce(rows[idx][1][2:].strip()))
                idx += 1
            return items, idx
        mapping: dict[str, Any] = {}
        while idx < len(rows) and rows[idx][0] == indent:
            key_part = rows[idx][1]
            if ":" not in key_part:
                idx += 1
                continue
            key, _, rest = key_part.partition(":")
            key, rest = key.strip(), rest.strip()
            if rest == "":
                if idx + 1 < len(rows) and rows[idx + 1][0] > indent:
                    value, idx = parse_block(idx + 1, rows[idx + 1][0])
                else:
                    value, idx = None, idx + 1
                mapping[key] = value
            elif rest.startswith("["):
                mapping[key] = _parse_inline_list(rest)
                idx += 1
            else:
                mapping[key] = _coerce(rest)
                idx += 1
        return mapping, idx

    if not rows:
        return {}
    value, _ = parse_block(0, rows[0][0])
    return value


def load_config(path: str | None = None) -> dict:
    path = path or os.path.join(ROOT, "config.yaml")
    with open(path, "r", encoding="utf-8") as fh:
        return load_yaml(fh.read())


def load_env() -> None:
    """Load ``.env`` (KEY=VALUE lines) into os.environ if present. Optional."""
    path = os.path.join(ROOT, ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


# --------------------------------------------------------------------------- #
# Filesystem / HTTP
# --------------------------------------------------------------------------- #
def abspath(rel: str) -> str:
    return rel if os.path.isabs(rel) else os.path.join(ROOT, rel)


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def http_get(url: str, headers: dict | None = None, retries: int = 3,
             timeout: int = 60, pause: float = 0.0) -> bytes:
    last = None
    hdrs = {"User-Agent": UA, "Accept": "application/json, text/plain, */*"}
    if headers:
        hdrs.update(headers)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
            if pause:
                time.sleep(pause)
            return data
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET failed after {retries} tries: {url} ({last})")


def http_get_json(url: str, headers: dict | None = None, retries: int = 3,
                  timeout: int = 60, pause: float = 0.0) -> Any:
    """GET and parse JSON regardless of declared content-type. None on hard failure."""
    try:
        raw = http_get(url, headers=headers, retries=retries, timeout=timeout, pause=pause)
        return json.loads(raw.decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001
        log(f"http_get_json failed: {url} ({exc})")
        return None


def write_json(path: str, obj: Any, indent: int | None = None) -> None:
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=indent, ensure_ascii=False)


def read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def num(val: Any, default: float = 0.0) -> float:
    """Coerce a possibly-string/None numeric to float."""
    if val is None or val == "" or val == "-":
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


def is_partial_run(cfg: dict) -> bool:
    """True when this run was restricted to a subset of leagues (``--league``).

    Whole-repo JSON writers use this to merge their fresh output over the
    previously published file instead of clobbering the leagues they skipped.
    """
    allk = cfg.get("_all_leagues")
    return bool(allk) and set(cfg.get("leagues", [])) != set(allk)


def should_merge(cfg: dict, fresh_by_league) -> bool:
    """True when this run did not produce fresh output for every configured league.

    Covers both an explicit ``--league`` subset run and a full run where a league
    yielded nothing (e.g. a network/geo-walled source like WNBA from a cloud CI
    IP). In either case the whole-file writers merge over the published file so the
    untouched leagues survive instead of being clobbered to empty.
    """
    if is_partial_run(cfg):
        return True
    configured = set(cfg.get("_all_leagues") or cfg.get("leagues", []))
    produced = set(k for k in fresh_by_league if k in configured)
    return produced != configured


def merge_existing(path: str, fresh: dict, leagues: list, container_key: str | None = None) -> dict:
    """Merge ``fresh`` (only the rebuilt leagues) over the file already at ``path``.

    If ``container_key`` is given the per-league maps live under
    ``obj[container_key]``; otherwise the object is keyed directly by league.
    """
    base = read_json(path) if os.path.exists(path) else {}
    if not isinstance(base, dict):
        base = {}
    if container_key:
        merged = dict(base)
        dest = dict(base.get(container_key) or {})
        src = fresh.get(container_key) or {}
        for lg in leagues:
            if lg in src:
                dest[lg] = src[lg]
        merged[container_key] = dest
        for k, v in fresh.items():
            if k != container_key:
                merged[k] = v
        return merged
    merged = dict(base)
    for lg in leagues:
        if lg in fresh:
            merged[lg] = fresh[lg]
    return merged
