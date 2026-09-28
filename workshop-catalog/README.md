# Silicon Workshop Catalog — Toolkit

This directory contains the tools to initialize a **Silicon Workshop Catalog**
in any project using GitHub Copilot.

## What it provides

- **`workshop-template/`** — silicon-agnostic scaffold for new workshops
- **`create-workshop` Copilot skill** — guided 3-step wizard that creates a new
  workshop from vendor/release/EVK selection with live Launchpad + certified
  device validation
- **`catalog.yaml`** — auto-created registry of workshops in your project

## Installation

Clone `canonical/silicon-workshops` once on your machine:

```bash
git clone https://github.com/canonical/silicon-workshops ~/silicon-workshops
```

Then, in any project where you want to manage Silicon Workshops:

```bash
cd /path/to/your/project
~/silicon-workshops/workshop-catalog/init
```

That's it. Open the project in VS Code with GitHub Copilot and type:

```
create-workshop
```

## Usage

The `create-workshop` skill guides you through three steps:

1. **Vendor** — choose from silicon vendors with a public Canonical kernel
2. **Ubuntu release** — choose from available series for that vendor
3. **EVK** — choose from Ubuntu-certified IoT devices for that vendor

The skill resolves the kernel tag from Launchpad automatically and creates
a ready-to-launch workshop directory.

## Updating

To get the latest skill and template:

```bash
cd ~/silicon-workshops
git pull
cd /path/to/your/project
~/silicon-workshops/workshop-catalog/init
```

Running `init` again will update the skill and template without overwriting
your existing workshops or `catalog.yaml`.
