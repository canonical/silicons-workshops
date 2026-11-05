#!/usr/bin/env python3
"""Create a Silicon Workshop from the bundled template, deterministically.

Copies assets/workshop-template/, substitutes every placeholder, renames the
dispatch files, keeps the right toolchain block, renders the snapcraft stanza
for the Ubuntu Core base, runs the static checks, and registers the workshop
in catalog.yaml. Nothing here is a judgement call: the same inputs always give
the same workshop, so a failure is a bug to fix, not noise to work around.

Usage (all values are derived by the skill from C3/Launchpad, see SKILL.md):
  python3 scripts/instantiate.py \
      --vendor mediatek --vendor-display MediaTek --soc genio-510 \
      --evk-board genio-510-evk --ubuntu-release jammy \
      --kernel-repo https://git.launchpad.net/~canonical-kernel/ubuntu/+source/linux-mtk/+git/jammy \
      --ref-type tag --ref Ubuntu-mtk-5.15.0-1038.45 --flavour mtk

Optional: --arch (default arm64), --soc-families a,b, --toolchain none|clang18|clang21,
--dest DIR, --catalog FILE (default ./catalog.yaml), --no-catalog.

Prints JSON on success; on failure prints the reason on stderr and exits 1.
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_workshop  # noqa: E402
import wslib  # noqa: E402

SOURCES_FILE = wslib.SKILL_DIR / "references" / "kernel-sources.json"


class Fail(Exception):
    pass


def table_toolchain(vendor: str, series: str) -> str | None:
    """Toolchain profile recorded for this vendor/series row, if any."""
    try:
        data = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
        return data["vendors"][vendor]["series"][series].get("toolchain")
    except (OSError, KeyError, ValueError):
        return None


def validate_inputs(a: argparse.Namespace) -> None:
    for label, value in (("vendor", a.vendor), ("soc", a.soc), ("evk-board", a.evk_board), ("flavour", a.flavour)):
        if not wslib.SLUG_RE.match(value):
            raise Fail(f"--{label} '{value}' must be lowercase letters, digits and hyphens")
    if a.ubuntu_release not in wslib.SERIES:
        raise Fail(f"--ubuntu-release must be one of {', '.join(wslib.SERIES)}")
    if a.ref_type not in ("tag", "commit", "branch"):
        raise Fail("--ref-type must be tag, commit or branch")
    if a.ref_type == "commit" and not re.fullmatch(r"[0-9a-f]{40}", a.ref):
        raise Fail("--ref must be a full 40-character SHA when --ref-type is commit")
    if wslib.CRED_RE.search(a.kernel_repo):
        raise Fail(
            "Credentials must never be embedded in the kernel repository URL. "
            "Use a git+ssh:// URL for private repositories; authentication is "
            "supplied at runtime via ssh-agent."
        )
    if not re.match(r"^(https?|git\+ssh|ssh|git)://", a.kernel_repo):
        raise Fail("--kernel-repo must be an https://, git+ssh:// or ssh:// URL")


def pick_dest(a: argparse.Namespace) -> Path:
    if a.dest:
        dest = Path(a.dest)
        if dest.exists():
            raise Fail(f"{dest} already exists")
        return dest
    first = Path(f"{a.vendor}-workshop")
    if not first.exists():
        return first
    second = Path(f"{a.vendor}-{a.soc}-workshop")
    if second.exists():
        raise Fail(f"both {first} and {second} already exist; pass --dest")
    return second


def substitution_map(a: argparse.Namespace, series_display: str, version: str, core: str) -> dict[str, str]:
    return {
        "<vendor>": a.vendor,
        "<Vendor>": a.vendor_display,
        "<soc>": a.soc,
        "<evk-board>": a.evk_board,
        "<series>": a.ubuntu_release,
        "<Series>": series_display,
        "<ubuntu-version>": version,
        "<ubuntu-release>": a.ubuntu_release,
        "<core-base>": core,
        "<kernel-repo-url>": a.kernel_repo,
        "<kernel-ref-type>": a.ref_type,
        "<kernel-ref>": a.ref,
        "<kernel-flavour>": a.flavour,
        "<toolchain-arch>": a.arch,
    }


def text_files(dest: Path) -> list[Path]:
    out: list[Path] = []
    for root in wslib.SUBSTITUTE_ROOTS:
        base = dest / root
        if base.is_file():
            out.append(base)
        elif base.is_dir():
            out.extend(p for p in sorted(base.rglob("*")) if p.is_file() and not p.is_symlink())
    return out


def register_catalog(catalog: Path, a: argparse.Namespace, dest: Path) -> bool:
    """Append the workshop to catalog.yaml. Returns False if already present."""
    path_value = f"{dest.as_posix().rstrip('/')}/"
    if catalog.exists():
        text = catalog.read_text(encoding="utf-8")
        if re.search(rf"(?m)^\s*path:\s*{re.escape(path_value)}\s*$", text):
            return False
        if not text.endswith("\n"):
            text += "\n"
    else:
        text = (
            "# Silicon Workshop Catalog\n"
            "# Machine-readable index for the BSP agent to discover and select workshops.\n"
            "# Add a new entry here each time you create a workshop with create-workshop.\n"
            "\n"
            "schema_version: 1\n"
            "\n"
            "workshops:\n"
        )
    families = [s.strip() for s in (a.soc_families or a.soc).split(",") if s.strip()]
    entry = [f"  - name: {dest.name}", f"    vendor: {a.vendor}", "    soc_families:"]
    entry += [f"      - {s}" for s in families]
    entry += [
        f"    evk: {a.evk_board}",
        f"    path: {path_value}",
        "    ubuntu_releases:",
        f"      - {a.ubuntu_release}",
    ]
    catalog.write_text(text + "\n".join(entry) + "\n", encoding="utf-8")
    return True


def instantiate(a: argparse.Namespace) -> dict:
    validate_inputs(a)
    series_display, version, core = wslib.SERIES[a.ubuntu_release]
    toolchain = a.toolchain or table_toolchain(a.vendor, a.ubuntu_release) or wslib.DEFAULT_TOOLCHAIN[a.ubuntu_release]
    if toolchain not in wslib.TOOLCHAINS:
        raise Fail(f"toolchain '{toolchain}' is not one of {', '.join(wslib.TOOLCHAINS)}")
    if not wslib.TEMPLATE_DIR.is_dir():
        raise Fail(f"bundled template not found at {wslib.TEMPLATE_DIR}")

    dest = pick_dest(a)
    shutil.copytree(wslib.TEMPLATE_DIR, dest, symlinks=True, ignore=shutil.ignore_patterns(".git"))

    try:
        # The snap name is the kernel flavour, never built from soc or board.
        snap = dest / "sdk/snap/snapcraft/snapcraft.yaml"
        snap.write_text(
            snap.read_text(encoding="utf-8").replace("linux-<vendor>-<soc>", f"linux-{a.flavour}"),
            encoding="utf-8",
        )

        subs = substitution_map(a, series_display, version, core)
        for p in text_files(dest):
            text = p.read_text(encoding="utf-8")
            for token, value in subs.items():
                text = text.replace(token, value)
            p.write_text(text, encoding="utf-8")

        # Keep exactly one toolchain block in the build-host hooks.
        for hook in ("setup-base", "check-health"):
            p = dest / ".workshop" / "series-build" / "hooks" / hook
            text, blocks = wslib.select_profile(p.read_text(encoding="utf-8"), toolchain)
            if toolchain not in blocks:
                raise Fail(f"{hook} has no 'toolchain:{toolchain}' block (found: {blocks})")
            p.write_text(text, encoding="utf-8")

        # Snapcraft: build-base, architecture stanza, kernel source path.
        snap.write_text(wslib.fix_snapcraft(snap.read_text(encoding="utf-8"), core, a.arch), encoding="utf-8")

        # Rename the dispatch files.
        (dest / ".workshop" / "vendor-series.yaml").rename(dest / ".workshop" / f"{a.vendor}-{a.ubuntu_release}.yaml")
        (dest / ".workshop" / "series-build").rename(dest / ".workshop" / f"{a.ubuntu_release}-build")
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise

    findings = check_workshop.run_checks(dest.resolve())
    if findings.errors:
        shutil.rmtree(dest, ignore_errors=True)
        detail = "; ".join(f"{e['file']}: {e['message']}" for e in findings.errors)
        raise Fail(f"generated workshop failed its own checks (template bug, nothing was kept): {detail}")

    registered = False
    if not a.no_catalog:
        registered = register_catalog(Path(a.catalog), a, dest)

    return {
        "workshop_dir": dest.as_posix(),
        "workshop_name": f"{a.vendor}-{a.ubuntu_release}",
        "definition": f"{dest.as_posix()}/.workshop/{a.vendor}-{a.ubuntu_release}.yaml",
        "core_base": core,
        "toolchain": toolchain,
        "catalog": None if a.no_catalog else a.catalog,
        "catalog_entry_added": registered,
        "warnings": findings.warnings,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--vendor", required=True)
    ap.add_argument("--vendor-display", required=True)
    ap.add_argument("--soc", required=True)
    ap.add_argument("--evk-board", required=True)
    ap.add_argument("--ubuntu-release", required=True)
    ap.add_argument("--kernel-repo", required=True)
    ap.add_argument("--ref-type", required=True)
    ap.add_argument("--ref", required=True)
    ap.add_argument("--flavour", required=True)
    ap.add_argument("--arch", default="arm64", choices=("arm64", "armhf"))
    ap.add_argument("--soc-families", default="")
    ap.add_argument("--toolchain", default="", choices=("",) + wslib.TOOLCHAINS)
    ap.add_argument("--dest", default="")
    ap.add_argument("--catalog", default="catalog.yaml")
    ap.add_argument("--no-catalog", action="store_true")
    args = ap.parse_args()
    try:
        result = instantiate(args)
    except Fail as exc:
        print(f"instantiate: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
