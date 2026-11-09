# Silicon Workshops

Reproducible Ubuntu kernel build environments for silicon partners, built with
the [`workshop`](https://snapcraft.io/workshop) tool.

## What's included

| Path | Purpose |
|------|---------|
| `workshop-catalog/skills/create-workshop/` | Agent skill that creates a new Silicon Workshop. Self-contained: `SKILL.md`, `scripts/`, `references/` and the workshop template under `assets/`. |
| `docs/` | Skill specification |
| `renesas/`, `qualcomm/`, `xilinx/` | Vendor workshops |

## Requirements

- Node.js 18+ (for `npx skills`), `python3` and `git`
- [`workshop` snap](https://snapcraft.io/workshop) to build: `sudo snap install workshop --classic`
- A skills-compatible coding agent (VS Code with GitHub Copilot, Claude Code, Codex, ...)
- Network access to `certification.canonical.com` and `launchpad.net`

## Install the skill

From your project directory, with the [skills CLI](https://github.com/vercel-labs/skills):

```bash
npx skills add canonical/silicons-workshops --skill create-workshop
```

Pick the agents you use when prompted, or name them: `-a github-copilot claude-code codex`.
Avoid `--agent '*'`: it creates a directory for every supported agent in your project.

The CLI copies the whole skill folder into your agent's skills directory
(for example `.agents/skills/` and `.claude/skills/`; VS Code reads both). Nothing
else is installed.

## Use the skill

In VS Code, open the project in the chat panel in Agent mode and type `/create-workshop`,
or describe the task ("create a workshop for the MediaTek Genio 510 EVK"); the skill's
trigger phrases load it automatically. For other agents, see how your agent
invokes a skill from its skills directory.

The skill asks, in order:

1. **Vendor**: vendors with certified EVKs in the Canonical Certification (C3) database
   and a buildable kernel source.
2. **EVK**: the certified boards for that vendor, with the kernel C3 certified them on.
3. **Ubuntu release**: the certified release first, marked `(certified)`. Other
   releases with a kernel source are offered as customizations and flagged as such.

It then generates `<vendor>-workshop/` in your project from the bundled template
(one deterministic script: substitution, toolchain for the series, snap definition,
static checks) and registers the workshop in `catalog.yaml`. The kernel ref is pinned
automatically: the certified kernel's tag, or the latest release tag, or a commit for
repositories that publish no tags.

If you ask for the build, the skill then launches the workshop, clones the kernel and
builds the `.deb` packages and the Ubuntu Core kernel snap. When a stage fails it
repairs the **tooling** (build scripts, hooks, packages) and tries again, for at most
5 repair iterations. It never edits the kernel tree, patches, the kernel ref or
`config/workshop.yaml`; a kernel error, a network or disk failure, or the same failure
twice stops the run with a report (`HANDOFF.md`, `REPAIR-LOG.md`).

To target something the skill does not offer (your own kernel repository, an EVK not
in C3), ask for it: the skill asks you for the repository, ref, flavour and series.

See [`docs/create-workshop-skill.md`](docs/create-workshop-skill.md) for the full specification.

## Build with the new workshop

The skill can do this for you. By hand:

```bash
cd <vendor>-workshop/

# First time: clone the kernel source
workshop run <vendor>-<series> -- clone-kernel

# Build kernel .deb packages
workshop run <vendor>-<series> -- kernel-build-debs

# Build kernel snap
workshop run <vendor>-<series> -- kernel-build-snap
```

Artefacts land in `out/deb/` and `out/snap/`.

## Update the skill

```bash
npx skills update create-workshop
```

Your existing `<vendor>-workshop/` directories are not touched.
