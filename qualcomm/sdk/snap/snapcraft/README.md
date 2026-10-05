# Snap Packaging SDK — deb → plugin:kernel path (contract §8)

This directory holds the snapcraft recipe for the Qualcomm kernel snap. Unlike
the renesas reference (which builds the snap from the kernel *source* tree's own
`snap/snapcraft.yaml`), Qualcomm uses the contract's **alternative deb →
plugin:kernel path**: `kernel-build-snap` reuses the deb-SDK Ubuntu debs
(`linux-image` + `linux-modules`) and assembles an Ubuntu Core initrd with
snapcraft's `initrd` plugin. No kernel recompile. See `../../../DESIGN.md`.

Layout:

```
snapcraft/
├── snap/snapcraft.yaml     # the recipe (type: kernel; kernel + initrd parts)
└── build-inputs/           # staged debs + dtb (generated at build time, gitignored)
```

Flow (driven by `sdk/snap/lib/pack.sh`):

1. `kernel-build-debs` produces `out/deb/linux-{image,modules}-*_arm64.deb`.
2. `kernel-build-snap` copies those debs (+ the device-tree, extracted from the
   image deb) into `build-inputs/`.
3. `snapcraft pack --destructive-mode --build-for=arm64` runs here: the `kernel`
   part unpacks the debs, regenerates module metadata with `depmod`, and lays
   out `vmlinuz`/`modules` for the `initrd` part, which builds `initrd.img`.
4. The `.snap` is staged to `out/snap/` and validated (`type: kernel` +
   `initrd.img` present).
