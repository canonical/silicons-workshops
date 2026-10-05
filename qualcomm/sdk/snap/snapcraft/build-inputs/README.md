# Snap SDK staging area

`kernel-build-snap` stages the deb-SDK output here before running snapcraft:

- `linux-image-*_arm64.deb`   (from `out/deb/`)
- `linux-modules-*_arm64.deb` (from `out/deb/`)
- `<device-tree>.dtb`         (extracted from the linux-image deb, if present)

The snapcraft recipe (`../snap/snapcraft.yaml`, `kernel` part) reads these via
`source: build-inputs`. Everything here is generated at build time and is
gitignored — do not commit staged debs.
