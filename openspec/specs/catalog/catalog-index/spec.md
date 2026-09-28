## Purpose

A machine-readable index at the catalog root that allows the BSP agent to
discover available workshops and select the best match for a given silicon
family without reading every workshop directory individually.

## ADDED Requirements

### Requirement: catalog.yaml exists at catalog root
The catalog root SHALL contain a `catalog.yaml` file listing every workshop
present in the catalog, with sufficient identity fields for silicon-family
matching.

#### Scenario: Agent discovers all workshops
- **WHEN** the BSP agent reads `catalog.yaml`
- **THEN** it can enumerate all available silicon workshops and their vendor/soc
  identity without traversing workshop subdirectories

### Requirement: Each catalog entry contains silicon identity fields
Every entry in `catalog.yaml` SHALL contain at minimum: `name`, `vendor`,
`soc_families` (list), `evk` (reference board name), `path` (relative directory
path), and `ubuntu_releases` (list of supported Ubuntu release names).

#### Scenario: Agent selects workshop by vendor
- **WHEN** BSP analysis identifies `vendor: mediatek`
- **THEN** the agent can filter `catalog.yaml` entries by `vendor` to find
  matching workshops without any other knowledge of the catalog layout

#### Scenario: Entry references correct workshop directory
- **WHEN** an agent reads the `path` field of a catalog entry
- **THEN** that path resolves to a valid workshop directory containing
  `config/workshop.yaml`

### Requirement: New workshops register in catalog.yaml
When a new workshop is created from the template, the catalog MUST be updated
with a new entry in `catalog.yaml` before the workshop is considered complete.

#### Scenario: Workshop creation updates catalog
- **WHEN** the create-workshop skill instantiates a new workshop
- **THEN** `catalog.yaml` contains a new entry for that workshop's silicon family
