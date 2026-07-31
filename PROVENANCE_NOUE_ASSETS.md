# Provenance of the Unreal Engine binary asset files under `pipeline/py/noue_master/`

This repository contains a small number of Unreal Engine–native binary asset files
(`.uasset` / `.uexp`, 17 pairs / 34 files) under `pipeline/py/noue_master/`. Because
these files use the same binary container format that Palworld's own game assets use,
we want to be explicit and proactive about what they are and are not.

## What they are not

Palworld's own game data — the several hundred files our conversion pipeline needs to
reference (materials, meshes, and other assets that belong to the base game) — is
**never bundled in this repository**. Instead, our pipeline extracts what it needs, at
conversion time, directly from **the user's own legally-owned, locally installed copy**
of Palworld (see `pipeline/py/pak_live_extract.py`). None of that data is copied into
source control, committed to this repository, or redistributed by us in any form.

## What they are

The 34 files in `noue_master/` are assets **we authored ourselves**:

- **Materials** (`M_VP_*.uasset` / `.uexp`, including the `LitMaster1S` / `LitMaster2S`
  variants and the `noue_variants/{Lit1S,Lit2S,Unlit1S,Unlit2S}/` staging copies): a
  small Unreal Engine material graph we built from scratch (a master Material with a
  single custom scalar parameter we named `ShadowLift`, plus MaterialInstanceConstant
  overrides), compiled ("cooked") by Unreal Engine's own compiler. They exist because
  our mod format requires a replacement material at a specific package path/slot name
  that matches what the target mesh expects — the *name* is a plain identifier string
  required for the mod to load, not proprietary content. The material logic itself
  (shading parameters, texture references) is ours. Generator script (present in this
  repository): `pipeline/py/ue_archive/09_build_noue_variants.py`. This was a one-time,
  developer-side build step; the standalone Unreal Engine cook pipeline it depended on
  (`pipeline/ue/`, an Unreal Editor project template) was intentionally deleted from this
  repository afterward, once the conversion pipeline moved to a UE-independent design
  (the current pipeline never invokes Unreal Engine at all — see "Independent
  verification" below for why we don't rely on re-running this script as our evidence).
- **Textures** (`t00.uasset` / `t00.uexp`, `t01.uasset` / `t01.uexp`, in both a 2048px
  seed form under `tex_src_2048/` and a 4096px derived form under `pak_extract_extra/`):
  built from images we created or sourced under a permissive license (CC0), imported
  into Unreal Engine and cooked the same way any Unreal Engine texture asset is
  produced. The 4096px form is a **deterministic, byte-for-byte reproducible**
  derivation of the 2048px seed — regenerating it from the seed using the generator
  script below yields an identical file, **and we have independently re-run this
  regeneration and confirmed the byte match** (see below). Generator script (present in
  this repository, pure Python, does not require Unreal Engine, and is re-runnable by
  anyone): `pipeline/py/devtool_make_t00_4096.py`.

## Why the file paths look like Palworld's own paths

The folder structure (e.g. `Player/ModelMaterials/MainShader/`) mirrors the *location*
inside the target game's package namespace where our replacement asset needs to be
placed for the mod to take effect — this is how Unreal Engine content mods generally
work (the mod's package path must match the path being overridden). The path string is
a plain identifier, not game content; it does not carry any of Palworld's copyrighted
material, textures, meshes, or code.

## Independent verification

We built a reproducible verification tool — `devtools/verify_noue_asset_provenance.py`
(pure Python, no third-party dependencies, no network access, no Unreal Engine
required) — so that this claim does not rest on our word alone. It performs two kinds
of checks against all 34 files, and anyone (including a SignPath reviewer) can run it
themselves:

### 1. Byte-for-byte regeneration (strongest evidence, 2 of the 34 files)

`python devtools/verify_noue_asset_provenance.py --regen-check` actually re-runs
`devtool_make_t00_4096.py` against the checked-in 2048px seed
(`noue_master/tex_src_2048/t00.*`) and confirms the output is **byte-identical** (SHA-256
match) to the checked-in 4096px derivation (`noue_master/pak_extract_extra/.../t00.*`).
This is not a claim we're asking to be trusted — it is a deterministic, pure-Python
transform that anyone can re-execute and check for themselves in seconds.

This does not extend to the other 32 files (the `M_VP_*` materials, `t01`, and the
`t00` 2048px seed itself): reproducing those from scratch would require re-running the
original Unreal Engine cook, and the Unreal Engine project template used for that
one-time build step was intentionally removed from this repository once our conversion
pipeline moved away from depending on Unreal Engine at all (it is UE-independent by
design; see the pipeline documentation). We are disclosing this limitation rather than
overstating what byte-reproduction alone can prove for those files, and rely on the
structural analysis below to cover them.

### 2. Structural analysis of all 34 files (import-table + shader-blob scan)

`python devtools/verify_noue_asset_provenance.py` parses the Unreal Engine cooked
package header (`FPackageFileSummary`) of every one of the 17 `.uasset` files and reads
its **import table** — the complete, exhaustive list of every external
package/object each file can possibly reference (this is a hard requirement of how
Unreal Engine serializes objects: any reference to something outside the current
package *must* go through an import-table entry — there is no other mechanism). We
verify that none of the 34 files reference anything outside of Unreal Engine's own
standard class namespace (`/Script/*`, present in every Unreal Engine project
regardless of game) and this project's own package path. No shared Palworld material,
texture, or function library is referenced anywhere.

We additionally scan every `.uexp` file — including the four ~357KB compiled shader
byte-code blobs, the largest and least-transparent files in the set — for any printable
string resembling a Palworld/game identifier (`pal`, `palworld`, `pocketpair`, `pocket`,
`monster`, case-insensitive). None are found. What *is* present in those blobs is
exactly what any Unreal Engine 5 material compilation produces for any project: generic
rendering-pipeline class names (`TBasePassPS...`, `FMaterialShaderMapContent`, ...) and
standard DXBC/DXIL shader container metadata (`dx.entryPoints`, `dx.version`, ...),
plus our own custom parameter name (`ShadowLift`) and standard built-in Unreal material
parameters — nothing else.

As a negative control, we ran the same tool against a genuine Palworld-authored
material instance extracted (and then deleted — not committed anywhere) from a
legitimate, locally-installed copy of Palworld. Unlike our 34 files, that genuine
Palworld asset's import table immediately showed several external package references to
Palworld's own shared assets (its parent master material and multiple textures) —
demonstrating that this analysis method actually distinguishes self-authored assets from
real game assets, rather than passing everything indiscriminately.

Both the regeneration check and the structural analysis are covered by an automated
regression test (`tests/test_noue_asset_provenance.py`) so this remains true going
forward, not just at the time of writing.
