## Purpose

A silicon-agnostic scaffold that every new Silicon Workshop is instantiated from,
ensuring structural and contractual conformance across all silicon families in
the catalog without requiring contributors to reconstruct the layout from scratch.

## ADDED Requirements

### Requirement: Template contains complete workshop directory structure
The workshop-template SHALL contain a complete, copy-ready directory layout
representing a conformant Silicon Workshop: `config/`, `sdk/common/`,
`sdk/deb/`, `sdk/snap/`, `.workshop/`, and `tools/`.

#### Scenario: All required directories present
- **WHEN** the template directory is listed
- **THEN** all of `config/`, `sdk/common/`, `sdk/deb/bin/`, `sdk/deb/lib/`,
  `sdk/snap/bin/`, `sdk/snap/lib/`, `sdk/snap/snapcraft/`, `.workshop/` are
  present

### Requirement: Template config contains labelled placeholders
The template `config/workshop.yaml` SHALL contain placeholder values for every
silicon-specific field, clearly labelled so an agent or contributor knows exactly
what to substitute. No real silicon values SHALL appear in the template config.

#### Scenario: Placeholder fields are identifiable
- **WHEN** an agent reads `workshop-template/config/workshop.yaml`
- **THEN** every silicon-specific value is a clearly-labelled placeholder
  (e.g. `<vendor>`, `<soc>`, `<kernel-flavour>`) and the file is valid YAML

### Requirement: Template SDK scripts are silicon-agnostic
The bash scripts under `sdk/` in the template SHALL read all silicon-specific
values from `config/workshop.yaml` and SHALL NOT hard-code any silicon vendor
name, SoC identifier, kernel flavour, or repository URL.

#### Scenario: New workshop runs kernel-build-debs from config alone
- **WHEN** `config/workshop.yaml` is populated with valid silicon values
- **THEN** `kernel-build-debs` reads those values and invokes `debian/rules`
  without requiring any script edits

### Requirement: Template Snap SDK owns its snapcraft.yaml
The template Snap SDK SHALL include a `snapcraft.yaml` skeleton under
`sdk/snap/snapcraft/` that uses `plugin: kernel` with
`kernel-ubuntu-debian-package: true`. The kernel source tree SHALL NOT be
required to ship a `snapcraft.yaml` for the snap build to succeed.

#### Scenario: Snap build uses Snapcraft Kernel plugin
- **WHEN** `kernel-build-snap` is run with a populated config
- **THEN** snapcraft is invoked against the `snapcraft.yaml` in `sdk/snap/snapcraft/`
  using `plugin: kernel` and `kernel-ubuntu-debian-package: true`

#### Scenario: No snapcraft.yaml required in kernel source
- **WHEN** the cloned kernel source tree contains no `snapcraft.yaml`
- **THEN** `kernel-build-snap` still succeeds using the SDK-owned `snapcraft.yaml`

### Requirement: Template provisioning hooks are silicon-agnostic
The `.workshop/` provisioning hooks (`setup-base`, `setup-project`,
`check-health`) SHALL install common Ubuntu kernel build dependencies and SHALL
NOT reference silicon-specific vendor tools by default. A placeholder comment
SHALL indicate where silicon-specific additions belong.

#### Scenario: Provisioning hook runs without silicon-specific content
- **WHEN** the template provisioning hooks are run on a fresh Ubuntu host
- **THEN** cross-toolchains, snapcraft, kernel build-deps, and rust are installed
  without error
