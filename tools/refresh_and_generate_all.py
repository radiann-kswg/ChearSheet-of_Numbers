from __future__ import annotations

import datetime as dt
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class RangeSpec:
    label: str
    start: int
    end: int


RANGES: list[RangeSpec] = [
    RangeSpec("0-99", 0, 99),
    RangeSpec("100-199", 100, 199),
    RangeSpec("200-299", 200, 299),
    RangeSpec("300-399", 300, 399),
    RangeSpec("400-499", 400, 499),
    RangeSpec("500-599", 500, 599),
    RangeSpec("600-699", 600, 699),
    RangeSpec("700-799", 700, 799),
    RangeSpec("800-899", 800, 899),
    RangeSpec("900-999", 900, 999),
]


def _number_file_path(n: int) -> Path:
    h = n // 100
    return ROOT / "numbers" / f"{h}xx" / f"{n:03d}.md"


def _fmt_mtime(path: Path) -> str:
    st = path.stat()
    ts = dt.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")
    return f"{path.as_posix()}\t{ts}\t{st.st_size}"


def _url_ok(url: str, timeout_s: float) -> bool:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "CheatSheet-of_Numbers/1.0 (tools/refresh_and_generate_all.py)",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            r.read(2048)
        return True
    except Exception as e:  # noqa: BLE001
        print("[net]", type(e).__name__, str(e))
        return False


def network_ok() -> bool:
    w_ok = _url_ok(
        "https://ja.wikipedia.org/w/api.php?action=query&titles=31&prop=info&format=json",
        timeout_s=8,
    )
    d_ok = _url_ok(
        "https://www.wikidata.org/w/api.php?action=wbgetentities&ids=Q31&format=json",
        timeout_s=8,
    )
    if w_ok and d_ok:
        print("[net] ok")
        return True
    print("[net] not ok")
    return False


def run_checked(args: list[str]) -> None:
    # Ensure consistent cwd
    proc = subprocess.run(args, cwd=ROOT)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed (exit={proc.returncode}): {' '.join(args)}")


def run_with_heartbeat(args: list[str], timeout_sec: float, label: str) -> None:
    start = time.time()
    last_beat = start

    proc = subprocess.Popen(args, cwd=ROOT)
    try:
        while True:
            rc = proc.poll()
            if rc is not None:
                if rc != 0:
                    raise subprocess.CalledProcessError(rc, args)
                return

            now = time.time()
            if now - start > timeout_sec:
                raise subprocess.TimeoutExpired(args=args, timeout=timeout_sec)

            if now - last_beat >= 15:
                elapsed = now - start
                print(f"[wait] {label} running... {elapsed:.0f}s", flush=True)
                last_beat = now

            time.sleep(1)
    finally:
        # If still running due to exception, terminate.
        if proc.poll() is None:
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass
            try:
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass


def main() -> None:
    python_exe = sys.executable

    print(f"[info] python: {python_exe}")
    print(f"[info] root:   {ROOT.as_posix()}")

    for r in RANGES:
        print("\n== range", r.label, "==")

        net = network_ok()
        mode = "online + refresh" if net else "offline (cache only)"
        print("[mode]", mode)

        before_start = _number_file_path(r.start)
        before_end = _number_file_path(r.end)
        print("[before] mtimes")
        print(_fmt_mtime(before_start))
        print(_fmt_mtime(before_end))

        base_args = [
            python_exe,
            "tools/generate_numbers.py",
            "--wikipedia-sections",
            "--only",
            r.label,
        ]

        def _run_generate(online_refresh: bool) -> None:
            args = list(base_args)
            if online_refresh:
                args += [
                    "--refresh-wikidata",
                    "--refresh-wikipedia",
                    "--refresh-wikipedia-sections",
                ]
            else:
                args += ["--offline"]

            # If network is flaky, urllib inside the generator may still stall.
            # Put an upper bound per range, then fall back to offline.
            timeout_sec = 30 * 60
            run_with_heartbeat(args, timeout_sec=timeout_sec, label=r.label)

        t0 = time.time()
        try:
            _run_generate(online_refresh=net)
        except subprocess.TimeoutExpired:
            if net:
                print("[warn] timeout during online refresh; retrying offline")
                _run_generate(online_refresh=False)
            else:
                raise
        except subprocess.CalledProcessError as e:
            if net:
                print(f"[warn] generator failed during online refresh (exit={e.returncode}); retrying offline")
                _run_generate(online_refresh=False)
            else:
                raise

        dt_s = time.time() - t0
        print(f"[ok] generated in {dt_s:.1f}s")

        after_start = _number_file_path(r.start)
        after_end = _number_file_path(r.end)
        print("[after] mtimes")
        print(_fmt_mtime(after_start))
        print(_fmt_mtime(after_end))

    print("\n== internal link check ==")
    run_checked([python_exe, "tools/check_internal_links.py"])
    print("[done] refresh/generate completed")


if __name__ == "__main__":
    main()
