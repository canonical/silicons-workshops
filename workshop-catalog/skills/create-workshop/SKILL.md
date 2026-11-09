---
name: create-workshop
description: >
  Create a Silicon Workshop for a silicon vendor and EVK, then build the kernel
  in it and repair the tooling until the build works. Selects the vendor, the
  certified EVK, the Ubuntu release and the kernel ref from the Canonical
  Certification (C3) database and live Launchpad sources, or accepts a custom
  target. Generates the workshop from a bundled template, runs the staged
  build (launch, clone, Debian packages, Ubuntu Core kernel snap) and fixes
  tooling failures within a fixed budget, never the kernel or its patches.
  Ends with a handoff report.
  WHEN: create workshop, new silicon workshop, add workshop, create kernel
  workshop, build kernel for EVK, build kernel for board, set up kernel build
  environment, new vendor workshop, create BSP workshop, add EVK workshop,
  create workshop for mediatek, create workshop for qualcomm, create workshop
  for renesas, create workshop for xilinx, repair kernel build workshop,
  workshop launch fails, kernel snap build fails, custom kernel target.
license: Apache-2.0
metadata:
  author: Canonical
  version: "2.0.0"
  summary: >
    Creates a Silicon Workshop for a vendor, EVK and Ubuntu release, builds the
    kernel in it, and repairs tooling failures within a bounded budget.
  tags:
    - silicon
    - kernel
    - workshop
    - ubuntu
    - bsp
compatibility: python3 and git. Building also needs the workshop snap (LXD) and about 25 GB of disk.
allowed-tools: python3 git workshop
---

# create-workshop

Takes the user from "I want a kernel build environment for this board" to a
working workshop and built kernel packages, with as little back-and-forth as
possible, and stops honestly when it cannot get there.

Paths in this skill (`scripts/`, `references/`, `assets/`) are relative to the
directory containing this `SKILL.md`. The user's project directory is where the
workshop is created and where commands run.

## Rules that never bend

1. **Never edit the kernel tree, patches, the kernel ref or `config/workshop.yaml`
   to make a build pass.** Repair is for tooling only: `.workshop/`, `sdk/`,
   `.gitignore`. A kernel compile error is reported, not fixed.
2. **At most 5 repair iterations** per workshop. `scripts/run_stages.py`
   enforces it, and stops on the same failure twice, on network or disk
   failures, and on anything that points into the kernel.
3. **Never answer "not supported" from a failed lookup.** If a script exits
   non-zero, say the check failed and stop. Never guess a list.
4. **Never embed credentials** in a URL. Private repositories use `git+ssh://`
   and the user's ssh-agent.
5. **Never modify the bundled `assets/workshop-template/`** or another workshop.
6. **Never claim a build is certified or validated** beyond what the data says.

## Overview

| Phase | What happens | How |
|---|---|---|
| 1. Select | vendor, EVK, Ubuntu release, kernel ref | `scripts/c3_lookup.py`, then ask |
| 2. Generate | workshop directory and `catalog.yaml` entry | `scripts/instantiate.py` |
| 3. Build and repair | launch, clone, `.deb`, snap, bounded repair | `scripts/run_stages.py` |
| 4. Report | what was built, what was repaired, what is unproven | handoff report |

---

## Phase 1: Select

Ask in sequence, never all at once. The reference is C3. The **default** is an
EVK that C3 certified, on the Ubuntu release and kernel it was certified on.
The user may deviate, but must be told when they do.

All lookups use public APIs (C3 and Launchpad), need only `python3`, and print
JSON. Where each vendor's kernel lives is data in `references/kernel-sources.json`;
never invent a repository URL or tag prefix.

**If a script exits non-zero**, say so and stop (rule 3).

### Step A: vendor

```bash
python3 scripts/c3_lookup.py vendors
```

Offer only `offerable: true` vendors, with the certified-EVK count. A series
with `state: private` (for example NVIDIA jammy) needs Launchpad access: ask
before re-running with `--ssh` (read-only `git ls-remote` with the user's own
key). For a vendor that is not offered, say why and offer the custom target.

### Step B: EVK

```bash
python3 scripts/c3_lookup.py evks --vendor <vendor>
```

One row per (EVK, series): `model`, `series`, `level`, `kernel_version` (what
C3 certified), `series_in_table`. Show model, certified series and kernel, and
ask. Normalize the model to `evk_board` (`Genio 510 EVK` -> `genio-510-evk`).
Mention `unmapped_releases` as unavailable. C3 labels can contradict the
certified kernel (a board labelled 24.04 certified on 5.15): show both.

### Step C: Ubuntu release

```bash
python3 scripts/c3_lookup.py series --vendor <vendor> --evk "<model exactly as in Step B>" [--ssh]
```

Offer the entries with `buildable: true`, certified first, with the ref:

```text
Which Ubuntu release?
  1. jammy (certified)   Ubuntu-mtk-5.15.0-1038.45
  2. noble               Ubuntu-mtk-6.8.0-1007.7
```

1. Certified and `ref_is_certified_pin`: label `(certified)`, show `ref.label`.
2. Certified, not pinned: label `(certified series)` and tell the user the
   `pin_note`: the ref offered is NOT the kernel C3 certified. Say plainly what
   C3 certified (for example 5.4) and what will be built (for example 5.15).
3. Not certified: a customization. Say C3 did not certify this EVK on that
   release; support there is not validated. Proceed once they confirm.
4. `build_validated`: has `deb` and `snap`, separately. For any `false`, say that
   target has not been built in a workshop for this vendor and release.
   `table_note`, when present, is evidence or a caveat: show it.
5. `state: private`: not offered; explain and offer `--ssh`.
6. `state: error`: the check failed, so the answer is UNKNOWN; list it as
   `<series> (could not check Launchpad)`.
7. `no-repo`, `no-tags`, `no-branch`: leave out. If it is the certified series,
   say "C3 certified `<EVK>` on `<series>`, but this skill has no buildable
   kernel source for it", and show the alternatives.

The chosen entry's `ref.type` and `ref.value` are the kernel ref (`commit` for
repositories with no release tags, such as Renesas resolute).

### Custom target

When the user wants something not offered, ask for: vendor, SoC, board, series
(focal, jammy, noble, resolute), kernel repository URL, kernel ref (tag or
commit; a branch only if they insist), and kernel flavour. Validate what can be:
`git ls-remote <repo> <ref>` (repository UNVERIFIED if it cannot run, not
invalid); the credential rule. The flavour and the toolchain cannot be checked
before the clone: the `deps` stage compares the kernel's own Build-Depends with
the build host after `clone-kernel` and repairs gaps. Custom targets are the
case the repair loop exists for. Then continue as below, with every
`build_validated` treated as false.

### Step D: confirm, derive, and ask about the build

Confirm vendor, EVK, release and ref, with every customization or unvalidated
note. Ask in the same message whether to **build now** (one build is about an
hour and needs about 25 GB; `.deb` and snap are separate builds). Derive the
rest without asking:

| Input | How to derive |
|-------|--------------|
| `vendor`, `vendor-display` | vendor key and `display` from Step A |
| `evk-board` | Step B |
| `soc` | from the model if it names a SoC family (`Genio 510 EVK` -> `genio-510`), else ask. Lowercase letters, digits, hyphens (`RZ/G2L EVKIT` -> `rz-g2l`) |
| `soc-families` | `soc`, unless the user lists more |
| `ubuntu-release` | series from Step C |
| `kernel-repo` | `repo_url` from Step C |
| `ref-type`, `ref` | `ref.type`, `ref.value` from Step C |
| `flavour` | `flavour` from Step C |
| `toolchain` | omit; the table row or the series decides. Pass `--toolchain` only for a custom target the user says needs it |

---

## Phase 2: Generate

One command; do not copy, substitute or rename by hand:

```bash
python3 scripts/instantiate.py --vendor <vendor> --vendor-display "<Vendor>" \
  --soc <soc> --evk-board <evk-board> --ubuntu-release <series> \
  --kernel-repo <url> --ref-type <tag|commit> --ref <ref> --flavour <flavour> \
  [--soc-families a,b] [--toolchain none|clang18|clang21]
```

It copies the bundled template, substitutes every placeholder, renames the
dispatch files, keeps the toolchain block for the series, renders the
`snapcraft.yaml` for the Ubuntu Core base, runs `scripts/check_workshop.py`,
and appends the `catalog.yaml` entry. It refuses credentials in the URL. On
failure it keeps nothing and prints why: that is a template bug, so report it
with the message instead of patching around it.

The output JSON has `workshop_dir` and `workshop_name`. If the user does not
want a build, stop here and give the next steps:

```text
cd <workshop_dir>
workshop launch <workshop_name>
workshop run <workshop_name> -- clone-kernel
workshop run <workshop_name> -- kernel-build-debs
workshop run <workshop_name> -- kernel-build-snap
```

`workshop` needs the project directory (`<workshop_dir>`) as the current
directory or `-p <dir>`; otherwise it prints "not a project".

---

## Phase 3: Build and repair

```bash
python3 scripts/run_stages.py run --workshop <workshop_dir>
```

Run it in a background terminal and wait: a build prints a heartbeat every two
minutes and logs to `<workshop_dir>/.repair/logs/`. Stages run in order and
finished ones are skipped: `check` (static), `launch`, `clone`, `deps` (kernel
Build-Depends against the build host), `deb`, `snap`. Use `--stages deb` to
build only one target.

It stops at the first failure and prints a verdict. Act on it:

| verdict | meaning | do |
|---|---|---|
| `continue` | every requested stage passed | go to Phase 4 |
| `fix-available` | a known tooling fix matches | run the `next` command (`apply-fix`), then `run` again |
| `diagnose` | unknown failure | read the log tail, find a **tooling** cause, edit only `.workshop/` or `sdk/`, then `record-fix --note "<cause and change>"`, then `run` again |
| `wait` | an earlier operation is still running | wait, then `run` again; never relaunch |
| `stop` | environment, kernel/patch, repeated failure, or budget used | go to Phase 4 with an escalation report |

Read `references/repair.md` before the first `diagnose` or `stop`. It has the
scope, what counts as tooling, how to write the note, and the report format.
`references/known-fixes.json` lists the signatures the script recognises.

`apply-fix` and `record-fix` check every change against the allowlist and
revert it when it touches anything else. If the kernel tree or
`config/workshop.yaml` would be the fix, that is a `stop`, not a repair.

---

## Phase 4: Report

Write `HANDOFF.md` in the workshop directory and summarise it to the user:

1. **Outcome** per target: `.deb`, snap. Built, failed, or not attempted. Not
   booted unless it was.
2. **What was built**: vendor, EVK, series, kernel repository, ref and commit.
   If the build is not the kernel C3 certified, say so in one plain sentence.
3. **Artifacts** with sizes and sha256 (`python3 scripts/run_stages.py report
   --workshop <workshop_dir>` lists them).
4. **Repairs**: summarise `REPAIR-LOG.md`; say which changes belong in the
   template or in `references/known-fixes.json`.
5. **Not proven**: the `build_validated` flags that were false, no hardware boot,
   no gadget or initrd check for the snap.
6. **If stopped**: the failing stage, the class (environment, kernel, repeated,
   budget), the log path, and what the user can do. Do not retry endlessly.

---

## Reference

- `references/repair.md`: repair scope, loop rules, report formats.
- `references/known-fixes.json`: error signatures and their fixes.
- `references/toolchain-notes.md`: toolchain per series, private repos, ssh.
- `references/kernel-sources.json`: vendor and series table (read by the scripts).
- `scripts/c3_lookup.py`, `instantiate.py`, `check_workshop.py`, `run_stages.py`:
  run them with `--help`.
