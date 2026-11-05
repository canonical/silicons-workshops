#!/usr/bin/env python3
"""Shared helpers for the create-workshop scripts (standard library only).

Imported by instantiate.py, check_workshop.py and run_stages.py. Not a command.
"""

from __future__ import annotations

import re
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = SKILL_DIR / "assets" / "workshop-template"

# series -> (Display name, Ubuntu version, Ubuntu Core base)
SERIES = {
    "focal": ("Focal", "20.04", "core20"),
    "jammy": ("Jammy", "22.04", "core22"),
    "noble": ("Noble", "24.04", "core24"),
    "resolute": ("Resolute", "26.04", "core26"),
}

# Toolchain profile = which "# >>> toolchain:<name>" block survives in the
# build-host hooks. The default follows the kernel generation that ships on
# each series; references/kernel-sources.json may override it per row, and
# check_workshop.py --kernel-src compares the choice with the kernel's own
# Build-Depends once the tree is cloned.
TOOLCHAINS = ("none", "clang18", "clang21")
DEFAULT_TOOLCHAIN = {
    "focal": "none",      # 5.4: no Rust, no clang in Build-Depends
    "jammy": "none",      # 5.15: only dwarfdump
    "noble": "clang18",   # 6.8: clang-18, bindgen-0.65, native rustc
    "resolute": "clang21",  # 7.x: clang-21, rustc >= 1.82
}

# Placeholders that must not survive instantiation.
PLACEHOLDER_RE = re.compile(
    r"<(vendor|Vendor|soc|evk-board|series|Series|ubuntu-version|ubuntu-release|"
    r"core-base|kernel-[a-z-]+|toolchain-arch)>"
)

# Files (relative to the workshop root) that carry placeholders to substitute.
SUBSTITUTE_ROOTS = ("config", ".workshop", "sdk/snap/snapcraft/snapcraft.yaml")

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
CRED_RE = re.compile(r"://[^/@\s]*:[^/@\s]*@")

BLOCK_BEGIN_RE = re.compile(r"^\s*#\s*>>>\s*toolchain:([a-z0-9]+)\s*$")
BLOCK_END_RE = re.compile(r"^\s*#\s*<<<\s*toolchain:([a-z0-9]+)\s*$")


# --------------------------------------------------------------------------
# Config reading
# --------------------------------------------------------------------------

def _strip_comment(value: str) -> str:
    out, quote = [], ""
    for i, ch in enumerate(value):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or value[i - 1].isspace()):
            break
        out.append(ch)
    return "".join(out).strip()


def _scalar(value: str):
    value = _strip_comment(value)
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    if value == "[]":
        return []
    if value == "{}":
        return {}
    return value


def mini_yaml(text: str) -> dict:
    """Parse the small, regular subset of YAML used by config/workshop.yaml.

    Nested mappings by indentation, scalars, inline `[]`, and block lists of
    scalars. Used only when PyYAML is not installed on the host.
    """
    root: dict = {}
    stack = [(-1, root)]
    last_key: dict[int, str] = {}
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if line.startswith("- "):
            # A block list belongs to the most recent key of the parent map.
            owner = stack[-1][1]
            key = last_key.get(id(owner))
            if key is not None:
                if not isinstance(owner.get(key), list):
                    owner[key] = []
                owner[key].append(_scalar(line[2:]))
            continue
        if ":" not in line:
            continue
        key, _, rest = line.partition(":")
        key = key.strip()
        last_key[id(parent)] = key
        if _strip_comment(rest) == "":
            child: dict = {}
            parent[key] = child
            stack.append((indent, child))
        else:
            parent[key] = _scalar(rest)
    return root


def load_config(ws: Path) -> dict:
    path = ws / "config" / "workshop.yaml"
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text) or {}
    except ImportError:
        return mini_yaml(text)


def cfg_get(cfg: dict, *keys, default=""):
    cur = cfg
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return default if cur is None else cur


# --------------------------------------------------------------------------
# Toolchain profile blocks
# --------------------------------------------------------------------------

def select_profile(text: str, profile: str) -> tuple[str, list[str]]:
    """Keep only the `toolchain:<profile>` block; drop the others.

    Returns (new_text, blocks_found). Text outside any block is kept. Marker
    lines are always removed. If the profile block is missing from a file that
    has blocks, the caller can tell from `blocks_found`.
    """
    out: list[str] = []
    found: list[str] = []
    current = None
    for line in text.splitlines(keepends=True):
        begin = BLOCK_BEGIN_RE.match(line)
        end = BLOCK_END_RE.match(line)
        if begin:
            current = begin.group(1)
            found.append(current)
            continue
        if end:
            current = None
            continue
        if current is None or current == profile:
            out.append(line)
    return "".join(out), found


# --------------------------------------------------------------------------
# snapcraft.yaml structure
# --------------------------------------------------------------------------

def arch_block(core_base: str, arch: str) -> str:
    """snapcraft architecture stanza for a cross build on an amd64 host."""
    if core_base in ("core20", "core22"):
        return (
            "# Cross build: compile on amd64, target "
            f"{arch}.\n"
            "architectures:\n"
            "  - build-on: amd64\n"
            f"    build-for: {arch}"
        )
    return (
        "# Cross build: compile on amd64, target "
        f"{arch}.\n"
        "platforms:\n"
        f"  {arch}:\n"
        "    build-on: [amd64]\n"
        f"    build-for: [{arch}]"
    )


_TOP_KEY_RE = re.compile(r"^[A-Za-z_-]+:")


def _drop_top_level(lines: list[str], key: str) -> tuple[list[str], int]:
    """Remove a top-level `key:` and its indented body. Returns (lines, index)."""
    out: list[str] = []
    idx = -1
    i = 0
    while i < len(lines):
        if re.match(rf"^{re.escape(key)}:", lines[i]):
            idx = len(out)
            i += 1
            while i < len(lines) and (
                not lines[i].strip() or lines[i][0] in " \t-"
            ) and not _TOP_KEY_RE.match(lines[i]):
                i += 1
            continue
        out.append(lines[i])
        i += 1
    return out, idx


def fix_snapcraft(text: str, core_base: str, arch: str) -> str:
    """Bring a kernel snapcraft.yaml to the shape snapcraft accepts.

    Idempotent. Fixes: `base:` -> `build-base:`, architecture stanza by core
    base, and `source: .` -> the kernel tree. Used by instantiate.py and by the
    repair step.
    """
    lines = text.split("\n")

    # base: -> build-base:   (a type: kernel snap is baseless)
    has_build_base = any(re.match(r"^build-base:", ln) for ln in lines)
    new: list[str] = []
    for ln in lines:
        if re.match(r"^base:\s", ln):
            if has_build_base:
                continue
            ln = re.sub(r"^base:", "build-base:", ln)
            has_build_base = True
        new.append(ln)
    lines = new
    lines = [
        re.sub(r"^build-base:\s*\S+", f"build-base: {core_base}", ln)
        for ln in lines
    ]

    block = arch_block(core_base, arch).split("\n")
    marker = next((i for i, ln in enumerate(lines) if ln.strip() == "#@SNAP_ARCH_BLOCK@"), -1)
    if marker >= 0:
        lines[marker:marker + 1] = block
    else:
        for key in ("platforms", "architectures"):
            lines, pos = _drop_top_level(lines, key)
        # Drop a leftover "Cross build" comment from an earlier rendering.
        lines = [ln for ln in lines if not ln.startswith("# Cross build: compile on")]
        at = next((i + 1 for i, ln in enumerate(lines) if re.match(r"^type:\s*kernel", ln)), len(lines))
        lines[at:at] = [""] + block

    text = "\n".join(lines)
    text = re.sub(r"(?m)^(\s*source:\s*)\.\s*$", r"\1../../../kernel-src", text)
    return text
