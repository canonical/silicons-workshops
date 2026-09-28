## Purpose

An agent skill that instructs a coding agent or contributor how to instantiate a
new conformant Silicon Workshop from the catalog template, given BSP analysis
inputs, without requiring knowledge of the internal workshop structure.

## ADDED Requirements

### Requirement: Skill accepts silicon identity as input
The create-workshop skill SHALL accept as input: silicon vendor name, SoC
family/identifier, reference EVK board name, Ubuntu release target(s), kernel
repository URL, kernel branch/tag/ref, kernel config flavour name, and target
architecture. All fields SHALL map directly to `config/workshop.yaml` fields.

#### Scenario: Skill invoked with minimal BSP inputs
- **WHEN** an agent invokes the skill with vendor, soc, board, kernel repo, kernel
  ref, and kernel flavour
- **THEN** the skill produces a complete workshop directory with all placeholder
  values substituted and no remaining `<placeholder>` tokens in config or
  workshop dispatch files

### Requirement: Skill copies template and substitutes config values
The skill SHALL copy `workshop-template/` to a new `<vendor>-workshop/`
directory and substitute all placeholder values in `config/workshop.yaml` and
`.workshop/*.yaml` with the provided silicon identity values.

#### Scenario: Workshop directory is named by vendor
- **WHEN** the skill creates a workshop for `vendor: mediatek`
- **THEN** the workshop directory is named `mediatek-workshop/` (or
  `<vendor>-<qualifier>-workshop/` when the catalog already contains a workshop
  for that vendor)

### Requirement: Skill generates a valid snapcraft.yaml from config
The skill SHALL generate `sdk/snap/snapcraft/snapcraft.yaml` for the new
workshop using `plugin: kernel` with `kernel-ubuntu-debian-package: true`,
setting `base`, `platforms`, and `kernel-ubuntu-kconfigflavour` from the
provided config values.

#### Scenario: Generated snapcraft.yaml uses Kernel plugin
- **WHEN** the skill generates `snapcraft.yaml` for a new workshop
- **THEN** it contains `plugin: kernel`, `kernel-ubuntu-debian-package: true`,
  and `kernel-ubuntu-kconfigflavour` set to the provided flavour value

#### Scenario: Generated snapcraft.yaml targets correct base
- **WHEN** the BSP input specifies `ubuntu.core_base: core26`
- **THEN** the generated `snapcraft.yaml` contains `base: core26`

### Requirement: Skill registers new workshop in catalog.yaml
After creating the workshop directory, the skill SHALL add a new entry to
`catalog.yaml` at the catalog root with the silicon identity fields populated.

#### Scenario: catalog.yaml updated after creation
- **WHEN** the skill completes successfully
- **THEN** `catalog.yaml` contains a new entry with the correct vendor, soc,
  evk, path, and ubuntu_releases fields

### Requirement: Skill validates no credentials in config
The skill SHALL verify that the generated `config/workshop.yaml` contains no
credentials, tokens, or passwords before completing. Private repository URLs
using `git+ssh://` are permitted; embedded credentials are not.

#### Scenario: Credential check passes for ssh URL
- **WHEN** `kernel.repository` is `git+ssh://git.launchpad.net/~team/repo`
- **THEN** the skill accepts it as a valid credential-free reference

#### Scenario: Credential check fails for embedded token
- **WHEN** `kernel.repository` contains a username:token pattern
- **THEN** the skill rejects the config and reports the violation
