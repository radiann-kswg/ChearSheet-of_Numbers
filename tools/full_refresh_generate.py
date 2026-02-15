from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_with_heartbeat(args: list[str], timeout_sec: float, label: str) -> int:
    start = time.time()
    last_beat = start

    proc = subprocess.Popen(args, cwd=ROOT)
    try:
        while True:
            rc = proc.poll()
            if rc is not None:
                return int(rc)

            now = time.time()
            if now - start > timeout_sec:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:  # noqa: BLE001
                    proc.kill()
                raise TimeoutError(f"timeout: {label} ({timeout_sec}s)")

            if now - last_beat >= 15:
                elapsed = now - start
                print(f"[wait] {label}... {elapsed:.0f}s", flush=True)
                last_beat = now

            time.sleep(1)
    finally:
        if proc.poll() is None:
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass


def main() -> int:
    py = sys.executable
    print(f"[info] python: {py}")
    print(f"[info] root:   {ROOT.as_posix()}")

    args = [
        py,
        "tools/generate_numbers.py",
        "--wikipedia-sections",
        "--refresh-wikidata",
        "--refresh-wikipedia",
        "--refresh-wikipedia-sections",
    ]

    # Full run can take a while depending on network/cache.
    rc = run_with_heartbeat(args, timeout_sec=3 * 60 * 60, label="full refresh+generate")
    if rc != 0:
        return rc

    rc = run_with_heartbeat([py, "tools/check_internal_links.py"], timeout_sec=10 * 60, label="internal link check")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
