from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote


_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


@dataclass(frozen=True)
class MissingLink:
    source_file: Path
    target_raw: str
    target_path: Path


def _is_external_link(target: str) -> bool:
    t = target.strip()
    if not t:
        return True
    if t.startswith("#"):
        return True
    lowered = t.lower()
    return lowered.startswith((
        "http://",
        "https://",
        "mailto:",
        "tel:",
        "data:",
    ))


def _split_target(target: str) -> str:
    t = target.strip()
    if t.startswith("<") and t.endswith(">"):
        t = t[1:-1].strip()

    t = unquote(t)

    if "#" in t:
        t = t.split("#", 1)[0]
    if "?" in t:
        t = t.split("?", 1)[0]

    return t.strip()


def _iter_markdown_files(repo_root: Path) -> list[Path]:
    ignore_parts = {".git", ".venv", "tools", "node_modules", "_template"}

    md_files: list[Path] = []
    for path in repo_root.rglob("*.md"):
        if any(part in ignore_parts for part in path.parts):
            continue
        md_files.append(path)

    # include instructions under .github even though it has a dot-dir
    github_dir = repo_root / ".github"
    if github_dir.exists():
        md_files.extend(github_dir.rglob("*.md"))

    # de-dup
    return sorted({p for p in md_files})


def check_internal_links(repo_root: Path) -> tuple[int, int, list[MissingLink]]:
    md_files = _iter_markdown_files(repo_root)

    links_checked = 0
    missing: list[MissingLink] = []

    for md_file in md_files:
        text = md_file.read_text(encoding="utf-8")
        current_dir = md_file.parent

        for match in _LINK_RE.finditer(text):
            raw = match.group(1)
            if _is_external_link(raw):
                continue

            target = _split_target(raw)
            if not target:
                continue

            # Only validate path-like links. If the link is just an anchor, it is already skipped.
            # If it's a bare word like "LICENSE" without extension, still check existence.
            target_path = Path(target)
            if target_path.is_absolute():
                # Treat absolute paths as external/invalid in this repo.
                continue

            resolved = (current_dir / target_path).resolve()
            links_checked += 1

            try:
                resolved.relative_to(repo_root.resolve())
            except ValueError:
                # points outside the repo; treat as missing.
                missing.append(MissingLink(md_file, raw, resolved))
                continue

            if not resolved.exists():
                missing.append(MissingLink(md_file, raw, resolved))

    return (len(md_files), links_checked, missing)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Check missing relative links in Markdown files.")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root directory (default: inferred from this script location).",
    )
    args = parser.parse_args(argv)

    repo_root: Path
    if args.repo_root is not None:
        repo_root = args.repo_root
    else:
        repo_root = Path(__file__).resolve().parents[1]

    repo_root = repo_root.resolve()

    files_scanned, links_checked, missing = check_internal_links(repo_root)

    print(f"Scanned markdown files: {files_scanned}")
    print(f"Checked relative links: {links_checked}")
    print(f"Missing links: {len(missing)}")

    if missing:
        print("\nFirst missing links:")
        for item in missing[:50]:
            try:
                rel_source = item.source_file.relative_to(repo_root)
            except ValueError:
                rel_source = item.source_file
            try:
                rel_target = item.target_path.relative_to(repo_root)
            except ValueError:
                rel_target = item.target_path
            print(f"- {rel_source}: ({item.target_raw}) -> {rel_target}")

        if len(missing) > 50:
            print(f"... and {len(missing) - 50} more")

        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
