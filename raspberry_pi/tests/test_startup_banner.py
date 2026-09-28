"""The startup banner must survive having no terminal.

This is a regression test for a bug that made the README's own instruction
unfollowable. The README says "open the printed URL", and the print reached
nobody: stdout is block-buffered (~8 KB) whenever it is not a TTY, so the
banner sat in the buffer and was discarded the moment the process was signalled
instead of exiting cleanly.

It hid because `python -m amr.main` in an interactive terminal is *line*
buffered and always worked. The only way to see the bug is to not be on a TTY --
which is exactly how a Pi is actually run: over SSH, under systemd, or with
nohup. So the test here deliberately does not use a TTY either.
"""

from __future__ import annotations

import signal
import subprocess
import sys
import time
import urllib.request

import pytest

REPO = str(__import__("pathlib").Path(__file__).resolve().parents[1])


def _run_and_capture(port: int, seconds: float = 9.0):
    """Start the server with stdout to a PIPE, then SIGTERM it.

    Returns (still_running, bytes_captured). A pipe is used rather than a temp
    file because a pipe is what SSH, systemd and nohup all present, and it is
    block-buffered the same way.
    """
    proc = subprocess.Popen(
        [sys.executable, "-m", "amr.main", "--mock", "--web",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=REPO,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    time.sleep(seconds)
    alive = proc.poll() is None
    if alive:
        # Signalled, not shut down: a clean exit would flush the buffer and
        # hide the very bug this test exists to catch.
        proc.send_signal(signal.SIGTERM)
    try:
        out, _ = proc.communicate(timeout=10)
    except Exception:
        proc.kill()
        out, _ = proc.communicate()
    return alive, (out or "")


def test_startup_banner_is_printed_without_a_terminal():
    """The URL the README tells you to open must actually be printed.

    Guarded against the false negative in both directions: the server must have
    been alive (otherwise this proves nothing) and the captured output must
    name a real route.
    """
    alive, out = _run_and_capture(8097)
    assert alive, "the server did not start; this test would prove nothing"
    assert out.strip(), (
        "no startup banner reached stdout. The README says 'open the printed "
        "URL', so a silent server leaves the operator with no way in. "
        "stdout is block-buffered when it is not a TTY, so the print needs "
        "flush=True."
    )
    assert "http://" in out, f"banner does not name a URL: {out!r}"
    assert "/command-center" in out, (
        f"banner should point at the Command Center: {out!r}"
    )
    assert "/applications" in out, (
        f"banner should point at the applications hub: {out!r}"
    )


def test_the_urls_the_banner_prints_really_answer():
    """A banner that prints a dead URL is worse than no banner at all.

    The banner is only worth printing if the links in it work, so this starts
    the server for real and fetches every path the banner advertises.
    """
    port = 8098
    proc = subprocess.Popen(
        [sys.executable, "-m", "amr.main", "--mock", "--web",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=REPO, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(80):
            time.sleep(0.25)
            try:
                urllib.request.urlopen(base + "/health", timeout=5).read()
                break
            except Exception:
                continue
        else:
            pytest.fail("server never came up")
        for path in ("/command-center", "/applications", "/dashboard", "/"):
            with urllib.request.urlopen(base + path, timeout=10) as r:
                assert r.status == 200, path
                assert r.read(), f"{path} returned an empty body"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
