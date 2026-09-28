# Silicon Workshops

Toolkit for creating reproducible Ubuntu kernel build environments for silicon partners using GitHub Copilot and the `workshop` tool.

## What's included

| Path | Purpose |
|------|---------|
| `workshop-template/` | Silicon-agnostic scaffold — copied into your project by `init` |
| `workshop-catalog/init` | One-shot installer script |
| `workshop-catalog/skills/` | Copilot skills installed into your project |
| `openspec/specs/` | OpenSpec specifications for the catalog system |

## Quick start

```bash
# Clone this repo once
git clone https://github.com/canonical/silicon-workshops ~/silicon-workshops

# In any project where you want Silicon Workshops:
cd /path/to/your/project
~/silicon-workshops/workshop-catalog/init

# Open in VS Code and type in Copilot chat:
#   create-workshop
```

## Skills installed by `init`

| Skill | Purpose |
|-------|---------|
| `create-workshop` | Guided wizard — vendor / release / EVK → ready-to-launch workshop |
| `openspec-propose` | Propose a new change with design + tasks |
| `openspec-apply-change` | Implement tasks from a change |
| `openspec-update-change` | Revise an existing change's plan |
| `openspec-sync-specs` | Sync delta specs to main specs |
| `openspec-archive-change` | Finalize and archive a completed change |
| `openspec-explore` | Thinking-partner mode for exploring ideas |

## Updating

```bash
cd ~/silicon-workshops && git pull
cd /path/to/your/project && ~/silicon-workshops/workshop-catalog/init
```

Running `init` again is safe — it skips files that already exist.
