#!/usr/bin/env python3
"""Sync the HowToCook ``dishes/`` snapshot into ``datasets/howtocook/dishes/``.

Downloads the ``Anduin2017/HowToCook`` source archive for a release tag and
mirrors its ``dishes/`` tree — recipe Markdown and images — into the datasets
directory. The snapshot is committed to the repo, so ingestion needs no network;
this script is run only to refresh or bump the tag. Re-running rebuilds
``dishes/`` from scratch, so files removed upstream disappear too.

Usage:
    uv run python scripts/howtocook.py 1.6.0
"""

from __future__ import annotations

import argparse
import shutil
import tarfile
import urllib.request
from io import BytesIO
from pathlib import Path

REPO = "Anduin2017/HowToCook"
ARCHIVE_URL = "https://github.com/{repo}/tarball/{tag}"
DEFAULT_DEST = Path("datasets/howtocook")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync the HowToCook dishes/ snapshot.")
    parser.add_argument("tag", help="upstream release tag, e.g. 1.6.0")
    parser.add_argument(
        "--dest",
        type=Path,
        default=DEFAULT_DEST,
        help=f"destination directory (default: {DEFAULT_DEST})",
    )
    args = parser.parse_args()

    url = ARCHIVE_URL.format(repo=REPO, tag=args.tag)
    print(f"Downloading {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "spectres-runtime"})
    with urllib.request.urlopen(request, timeout=60) as response:
        archive = response.read()

    dishes_dir = args.dest / "dishes"
    if dishes_dir.exists():
        shutil.rmtree(dishes_dir)

    count = 0
    with tarfile.open(fileobj=BytesIO(archive), mode="r:gz") as tar:
        for member in tar.getmembers():
            # Members carry a top-level prefix like ``HowToCook-<sha>/``; keep
            # only files under ``dishes/`` and strip that prefix.
            parts = Path(member.name).parts
            if not member.isfile() or len(parts) < 2 or parts[1] != "dishes":
                continue
            extracted = tar.extractfile(member)
            if extracted is None:
                continue
            target = args.dest.joinpath(*parts[1:])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(extracted.read())
            count += 1

    print(f"Synced {count} files into {dishes_dir}/")


if __name__ == "__main__":
    main()
