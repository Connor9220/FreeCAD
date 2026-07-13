# Cut Direction: Climb/Conventional vs CW/CCW

## STATUS

PROPOSED

## Why it is a priority

Several operations expose a raw `CW`/`CCW` "Direction" property to the user
(Profile, Deburr, and internally Helix/ThreadMilling) instead of the
tool-agnostic `Climb`/`Conventional` concept machinists actually think in.
Worse, the operations that *do* expose `Climb`/`Conventional` (PocketBase,
MillFacing, Waterline, Surface, RotarySurface, ThreadMilling) hardcode which
physical rotation direction "Climb" maps to — they never consult the Tool
Controller's `SpindleDir`. So if a user sets `SpindleDir = Reverse`, every
one of those operations silently cuts the opposite of what `CutMode` claims.

Separately, there is currently no way to represent a non-rotating tool
(plasma, laser, drag knife) at all. `Climb`/`Conventional` is physically
meaningless without a spindle, but nothing in the property model or the UI
reflects that — a user with a non-rotating tool would still be shown a
`Climb`/`Conventional` (or `CW`/`CCW`) choice that doesn't correspond to
anything real.

## Background / current state

- `Path.Op.Base.Compass` ([Base.py:1281](../../Path/Op/Base.py)) already
  implements the CW/CCW ⇄ Climb/Conventional conversion, driven by
  `spindle_dir` + `cut_side` (`Compass._expected_cut_mode`), plus separate
  `AREA`-operation-type helpers (`get_step_direction`, `get_cutting_direction`)
  for raster/zigzag patterns. It is used in exactly **one** place today:
  `Helix.py:50` (`_caclulatePathDirection`).
- `ToolController.SpindleDir` ([Controller.py:229](../../Path/Tool/Controller.py))
  already has a `Forward` / `Reverse` / `None` enum. Nothing currently sets it
  to `None` automatically — it defaults to `Forward` regardless of tool type.
- `ToolBit.can_rotate()` ([base.py:1084](../../Path/Tool/toolbit/models/base.py)),
  overridden by `RotaryToolBitMixin` (→ `True`) and by `Probe` (→ `False`
  explicitly). Every existing cutting tool model (endmill, ballend, drill,
  etc.) is rotary; no plasma/laser/drag-knife tool model exists yet.
- `Machine.toolheads[i].capabilities.can_rotate` ([machine.py:385-478](../../Machine/models/machine.py))
  already models `ROTARY` (`True`) vs `LASER`/`WATERJET`/`PLASMA` (`False`)
  at the machine-configuration level, but is not consulted by any operation,
  `Compass`, or `ToolController` today — it's only read by the post-processor
  (`Processor.py:1140`, itself tagged `# FIXME: should be an annotation`
  because there's no per-operation toolhead-index resolution yet for
  multi-toolhead machines).
- **History warning**: `Direction` briefly held `Climb`/`Conventional` text
  during part of the v1.0 cycle (PR#14364), and Helix's `onDocumentRestored`
  ([Helix.py:539-546](../../Path/Op/Helix.py)) carries a permanent migration
  to repair files saved during that window. This is why the design below
  keeps `Direction` and `CutMode` as two properties whose meaning never
  changes, rather than one property whose valid-value-set is swapped.

## Rotation capability: `toolCanRotate(obj)`

Single AND gate, to be added once as a shared helper (`Path.Op.Base`):

```
rotating = tool.can_rotate() and (machine.toolheads[0].can_rotate if Job.Machine else True)
```

- Tool-level is authoritative: a plasma torch doesn't climb-mill regardless
  of what it's bolted to.
- Machine-level only narrows further, and is optional — most jobs have no
  `Machine` configured, so it defaults permissive (`True`).
- `toolheads[0]` mirrors the existing (FIXME'd) precedent in `Processor.py`;
  real per-operation toolhead selection on multi-toolhead machines is a
  separate, later problem.

This feeds `ToolController.SpindleDir`: forced to `None` (read-only) when
`False`, defaults to `Forward` (editable `Forward`/`Reverse`) when `True`.

## Truth table — which ops need which property

| Operation | Path shape | `Direction` (CW/CCW) | `CutMode` (Climb/Conventional) | Notes |
| --- | --- | --- | --- | --- |
| Profile | perimeter offset | Always; editable when tool doesn't rotate | Editable when tool rotates | Has a separate `Side`/`isHole` bug — see below |
| Helix | perimeter offset (circular) | Always; read-only/derived when tool rotates | Editable when tool rotates | Already wired to Compass — reference implementation |
| ThreadMilling | perimeter offset (helical) | **Never** — no non-rotating thread mill exists | Editable — always (see special case below) | `isToolSupported` requires `Diameter`+`Crest`, i.e. always a rotary thread-mill bit; `toolCanRotate()` is trivially `True` |
| Deburr | perimeter offset (edge break) | **Never** — chamfer/countersink geometry only | Editable — always (see special case below) | Offset comes from `CuttingEdgeAngle`/`TipDiameter`/`FlatRadius`; a plasma/laser/drag-knife can't bevel an edge this way even though nothing structurally blocks it |
| MillFacing / MillFace | area raster/zigzag/spiral | Never (no single shape winding) | Editable when tool rotates; hidden otherwise | `Compass` AREA-type helpers already exist and are unused |
| PocketBase / Pocket / PocketShape | area offset/zigzag pocketing | Never | Editable when tool rotates; hidden otherwise | `CutMode` hardcoded today; needs Compass wiring |
| Waterline | area (per-Z-level 3D contour rings) | Never | Editable when tool rotates; hidden otherwise | Same |
| Surface | area (3D raster/offset) | Never | Editable when tool rotates; hidden otherwise | Same |
| RotarySurface | area (4th-axis wrapped raster) | Never | Editable when tool rotates; hidden otherwise | Same |
| Engrave | centerline (Profile with offset permanently 0) | Already functionally correct via `Reverse` bool ([Engrave.py:264](../../Path/Op/Engrave.py#L264)) → `orientWire(forward=...)`; **proposed: rename to `Direction` enum (CW/CCW) for naming consistency** — trivial 1:1 mapping (`Reverse=False → CW`, `Reverse=True → CCW`), see caveat below | Never — no offset means no "side" to be climb/conventional about, regardless of tool rotation | Not a distinct category from Profile — same op family at offset=0. Direction still matters here for real, tool-agnostic reasons: laser/plasma pierce point + thermal buildup, drag-knife blade trail |
| Vcarve | centerline (V-groove) | Not currently exposed — same reasoning as Engrave would suggest it should be, unverified | Never | Rotary-only in practice (V-bit-specific plunge-depth geometry) *if* that holds — not yet verified the way ThreadMilling/Deburr were; don't assume |
| Slot | outlier — see below | Has `ReverseDirection`, but interacts with `CutPattern` in a way that needs resolving first | Unclear — depends on whether `ExtendRadius` creates genuine off-center (asymmetric) engagement | **Do not categorize yet** — flagged for dedicated investigation |
| Drilling / Tapping / Probe | point / plunge | Never | Never | No lateral path at all |
| Custom | opaque user g-code | Never | Never | Framework can't reason about it |
| Adaptive | area, variable engagement | Not exposed (internal `"CCW"` hardcode) | Not exposed today | Third-party adaptive-clearing algorithm; direction is an internal implementation detail, not a user property. **Flagged for a follow-up epic, out of scope here.** |

Revised rule of thumb — two independent axes, not one op-type lookup:

- **`Direction` (CW/CCW / forward-reverse) is needed by any op that follows
  a defined path at all**, essentially regardless of tool rotation or
  offset. Even a purely symmetric, non-rotating-tool-eligible op like
  Engrave needs it — for pierce-point placement, thermal/heat-affected-zone
  direction (laser/plasma), and drag-knife blade-trail orientation. Only
  point/plunge ops (Drilling, Tapping, Probe) and opaque ops (Custom)
  legitimately need neither.
- **`CutMode` (Climb/Conventional) additionally requires the tool to rotate
  *and* the cut to be asymmetric** (material removed predominantly from one
  side of the path — an offset/perimeter cut, or an area-clearing pass).
  Symmetric/centerline cuts (Engrave, and likely Vcarve — see below) never
  get `CutMode`, because there's no "side" for climb vs. conventional to be
  relative to, no matter the tool.
- Area-clearing ops (MillFacing, PocketBase family, Waterline, Surface,
  RotarySurface) are inherently asymmetric per-pass, so they always get
  `CutMode` when rotating; they never get a standalone `Direction` since
  there's no single shape winding to name.
- **Open nuance, not resolved here**: Profile itself can be run at
  `UseComp = False`, `OffsetExtra = 0` — i.e. a pure centerline pass, same
  as Engrave. In that specific configuration `CutMode` is arguably moot even
  for a rotating endmill. Whether `CutMode`'s visibility should react to the
  *current offset value*, not just `toolCanRotate()`, is left as a follow-up
  question rather than solved in this pass.

**Naming consistency: Engrave's `Reverse` → `Direction`.** Proposed rename
from a bare `App::PropertyBool` to the same `App::PropertyEnumeration`
(`CW`/`CCW`) shape used elsewhere, so the property model reads the same
across ops. Migration is a direct 1:1 value mapping
(`Reverse=False → CW`, `Reverse=True → CCW`, matching `orientWire`'s own
`forward=True → clockwise` convention) — no Compass involvement needed,
since this is a pure rename/re-typing, not a Climb/Conventional question
(Engrave never gets `CutMode`, per above).

One caveat before committing to it: `orientWire`'s `forward` is computed via
a shoelace-formula signed area over whatever edges are present, so it's
well-defined even for **open** wires (e.g. engraving the letter "I" — a
single open stroke enclosing no area). Renaming works functionally either
way, but "CW"/"CCW" reads oddly for a shape that doesn't enclose an area,
where a plain boolean like "Reverse" doesn't imply winding at all. Worth a
UX call, not just a migration mechanics call.

**Special cases: ThreadMilling and Deburr.** Both are perimeter/offset ops,
but neither needs a raw `Direction` (CW/CCW) property, because neither has a
real non-rotating use case:

- **ThreadMilling** — `isToolSupported` requires `Diameter`+`Crest`, i.e.
  always a rotary thread-mill bit. `toolCanRotate()` is trivially `True`, so
  the visibility toggle never triggers. Its existing `Direction` property
  already stores `"Climb"`/`"Conventional"` text
  ([ThreadMilling.py:83-84](../../Path/Op/ThreadMilling.py#L83-L84)) — it's
  correctly Climb/Conventional today, just misleadingly named. Its actual bug
  is the same one PocketBase/MillFacing/etc. have: `threadSetupInternal`/
  `threadSetupExternal` ([ThreadMilling.py:130-158](../../Path/Op/ThreadMilling.py#L130-L158))
  pick `G2`/`G3` from `(ThreadOrientation, Direction)` alone, never consulting
  `SpindleDir` — `ThreadOrientation` (Left/Right Hand) plays the same role
  `isHole` plays for Profile: one input to the physical-direction lookup, not
  something the user needs a second raw property for. Fix = route through
  `Compass`+`SpindleDir` like the area ops; optionally rename `Direction`→
  `CutMode` for consistency (safe, since the values' meaning never changes —
  unlike the PR#14364 case — but not required for correctness).
- **Deburr** — nothing in code structurally blocks a non-rotating tool
  (no `isToolSupported` override, just `hasattr(tool, "Diameter")`), but the
  offset math (`toolDepthAndOffset`, [Deburr.py:53-91](../../Path/Op/Deburr.py#L53-L91))
  is chamfer/countersink bevel geometry — a plasma/laser/drag-knife can't cut
  a bevel that way, so nobody would assign one in practice. Treat it like
  ThreadMilling: only needs `CutMode`, no raw `Direction` fallback. Unlike
  ThreadMilling it currently has *no* `CutMode`/Climb-Conventional property
  at all — its raw `CW`/`CCW` `Direction` needs to become the hidden,
  Compass-derived property, with a new `CutMode` as the sole user-facing
  control. Adding an `isToolSupported` gate (reject non-chamfer tools) would
  be a reasonable companion tightening but is a separate concern from
  direction handling.

## Outlier requiring investigation: Slot

Slot ([Slot.py](../../Path/Op/Slot.py)) doesn't fit the Engrave pattern despite
looking similar at a glance (it has `ReverseDirection`, a boolean like
Engrave's `Reverse`). Rotary-only is a safe assumption — there's no
non-rotary use case for slotting the way there is for Profile/Engrave — but
that alone doesn't settle whether `CutMode` applies:

- **No stepover/width property exists.** The tool's own diameter defines the
  slot width; it's a single pass. For a *straight* slot the cutter engages
  nearly its full width at once — climb on one wall, conventional on the
  other, simultaneously. There's no single climb/conventional designation
  for that, same reasoning as Engrave.
- **But `ExtendRadius`** ("For arcs/circular edges, offset the radius for
  the toolpath") implies arc-mode slots can run off-center from the
  reference edge — an asymmetric annular cut, structurally like Helix.
  If so, `CutMode` *would* apply there.
- **`CutPattern` (`Directional`/`Bidirectional`) already has Compass-shaped
  behavior that predates this epic**: `Directional` repeats the same
  direction on every Z-depth pass ([Slot.py:750-754](../../Path/Op/Slot.py#L750-L754));
  `Bidirectional` alternates direction every other pass to skip the retract
  ([Slot.py:756-760](../../Path/Op/Slot.py#L756-L760)). If the arc/off-center
  case does make `CutMode` meaningful, `Bidirectional` is silently
  alternating climb and conventional pass-to-pass today with no indication
  to the user — exactly the kind of implicit behavior this epic exists to
  surface.

**Not categorized in the truth table above pending this investigation.**
Needs someone to confirm, with an actual off-center arc slot, whether the
resulting cut is genuinely asymmetric before deciding whether Slot needs
`CutMode` (Compass-wired, area-op style) on top of its existing `Direction`
equivalent.

## Task panel exposure audit

The App-layer visibility plan in "Rotation capability" above (`setEditorMode`
hidden/read-only, driven by `toolCanRotate()`) only affects the generic
**Property Editor** tree. It does **not** automatically affect the
hand-built **Task Panel** dialogs — each op's `Path/Op/Gui/<Op>.py` binds
specific named widgets from a `.ui` file to specific properties via its own
`comboToPropertyMap` / `getFields` / `setFields`. A property being hidden at
the App layer doesn't hide or show anything on the task panel; that has to
be coded per op, separately, in the Gui layer.

Checked every op that touches `Direction`/`CutMode` today:

| Operation | `Direction` on task panel? | `CutMode` on task panel? |
| --- | --- | --- |
| Helix | No — property editor only | Yes (`cutMode` combo, [Gui/Helix.py:64](../../Path/Op/Gui/Helix.py#L64)) |
| Profile | Yes (`direction` combo, unconditional, [Gui/Profile.py:65](../../Path/Op/Gui/Profile.py#L65)) | N/A — property doesn't exist yet |
| Deburr | Yes (`direction` combo, unconditional, [Gui/Deburr.py:66](../../Path/Op/Gui/Deburr.py#L66)) | N/A — property doesn't exist yet |
| ThreadMilling | Yes (`opDirection` combo — semantically `CutMode`, [Gui/ThreadMilling.py:84](../../Path/Op/Gui/ThreadMilling.py#L84)) | Same property/widget |
| PocketBase / MillFacing / RotarySurface | N/A | Yes (`cutMode` combo, each) |
| **Waterline** | N/A | **No** — property exists, not wired to any task panel widget |
| **Surface** | N/A | **No** — same gap |
| Engrave | No (`Reverse` — property editor only) | N/A |
| Slot | Yes (`reverseDirection` checkbox, unconditional) | N/A |

Implications:

- Every op where a Direction/CutMode toggle is added (Profile, Deburr, and
  the rename for Engrave) needs matching **`.ui` + Gui/\*.py** work, not just
  App-layer property/Compass changes — a new widget, wired into
  `comboToPropertyMap`, plus `setVisible`/`setEnabled` calls gated on
  `toolCanRotate()`. Helix's `.ui` (`PageOpHelixEdit.ui`) already has a
  `cutMode` combo and can serve as the template.
- Waterline and Surface missing `CutMode` from their task panels is a
  **pre-existing bug independent of this epic** — worth fixing regardless of
  how the Compass-wiring work (step 4) lands, since right now those two
  ops' primary cut-direction control is only reachable through the raw
  property editor.

## Known bug: Profile `Side` vs `isHole`

`Profile.areaOpPathParams` ([Profile.py:424-438](../../Path/Op/Profile.py))
flips `Direction` based only on `isHole` (is this loop an interior hole vs.
an exterior island) — it never looks at `obj.Side` (Inside/Outside) at all:

```python
if isHole:
    direction = "CW" if obj.Direction == "CCW" else "CCW"
else:
    direction = obj.Direction
```

But per `Compass._expected_cut_mode`, Climb/Conventional is a function of
**cut side + spindle rotation + path direction together**. Today, flipping
`obj.Side` while leaving `Direction` unchanged silently flips actual
Climb/Conventional with no indication to the user (there's no `CutMode`
property yet to even notice on).

Fix, once `CutMode` exists on Profile: per feature, compute
`effective_side = flip(Side) if isHole else Side`, then run
`(SpindleDir, effective_side, CutMode)` through `Compass` to get that
feature's `Direction`. This generalizes the existing `isHole` hack instead of
bypassing `Side`.

Separately (not a direction bug, a pre-existing limitation): `Side` is a
single **op-level** property, but one Profile op can reference multiple Base
features. Mixed "cut this loop outside, that loop inside" within one
operation isn't representable today. Out of scope for this pass — would be
its own "per-base Side override" feature.

## Migration

Two property-shape cases, both use `Compass._expected_cut_mode` /
`Compass.path_dir` for the math — no new geometry logic needed:

- **Ops with only raw `Direction` today, need `CutMode` added**: on load,
  add `CutMode` if missing, back-compute its value from the existing
  `Direction` + `Side` + `SpindleDir` via `Compass._expected_cut_mode`.
  - **Profile**: after migration, `Direction` stays user-editable when the
    tool doesn't rotate (real fallback use case), read-only/derived
    otherwise — the full visibility toggle.
  - **Deburr**: after migration, `Direction` becomes permanently hidden/
    derived — there's no legitimate non-rotating fallback (see special case
    above), so it's a degenerate case of the same pattern with the toggle
    always resolving one way.
- **Ops with only `CutMode` today, hardcoded to one rotation** (PocketBase,
  MillFacing, Waterline, Surface, RotarySurface, and ThreadMilling's
  `Direction`, which is semantically `CutMode` already): no property
  migration needed, but behavior changes for any saved job with
  `SpindleDir = Reverse` — those were silently cutting the opposite of what
  `CutMode`/`Direction` claimed. Routing through Compass is a correctness
  fix, not something to migrate around; call it out in release notes rather
  than special-casing old files.

`SpindleDir` itself: existing Tool Controllers all currently read `Forward`
(the pre-existing default) and reference only rotary tool models, so
`toolCanRotate()` evaluates `True` for every pre-existing document — no
forced `SpindleDir` rewrite needed on load.

## Work plan / sequencing

1. `toolCanRotate(obj)` helper + wire it into `ToolController` (`SpindleDir`
   forced to `None`/read-only when `False`).
2. Fix Profile's `Side`/`isHole` direction bug (real correctness bug,
   independent of the property-visibility work).
3. Add the `Direction`/`CutMode` dual-property + visibility-toggle pattern
   (generalizing what Helix already does) as a shared mixin/helper.
   - Profile: full toggle, driven by `toolCanRotate()`.
   - Deburr: add `CutMode`, wire `Direction` as permanently hidden/derived
     (degenerate case of the same helper — no `isToolSupported` gate added
     in this step; that's a separate, optional tightening).
4. Route PocketBase, MillFacing, Waterline, Surface, RotarySurface,
   ThreadMilling through Compass instead of their hardcoded Climb→rotation
   mapping; hide `CutMode` entirely when `toolCanRotate()` is `False` (moot
   for ThreadMilling and Deburr, always `True` in practice, but keep it
   consistent with the rest of this group).
5. Migration code for each op touched in steps 3–4.
6. Investigate Slot's `ExtendRadius`/arc off-center behavior to settle
   whether it needs `CutMode`; verify Vcarve is actually rotary-only before
   assuming it needs no changes (same mistake already made twice this pass
   for ThreadMilling and Deburr — don't repeat it by skipping verification).
7. Rename Engrave's `Reverse` (bool) → `Direction` (CW/CCW enum) for naming
   consistency, pending the open-wire UX call above; trivial migration.
8. Task-panel (`.ui` + `Gui/*.py`) work for every property added/toggled in
   steps 3 and 7 — App-layer visibility does not propagate to task panel
   widgets, see "Task panel exposure audit". Fix the pre-existing
   Waterline/Surface `CutMode`-not-on-task-panel gap in the same pass since
   it touches the same widgets.

## Scope

| In | Out |
| --- | --- |
| `toolCanRotate()` AND-gate helper | Multi-toolhead-per-machine resolution (stays `toolheads[0]`, matches existing Processor.py FIXME) |
| `SpindleDir` forced to `None` for non-rotating tools | Adding plasma/laser/drag-knife `ToolBit` models themselves |
| Profile `Side`/`isHole` direction bug fix | Per-base `Side` override (mixed inside/outside in one Profile op) |
| Direction/CutMode split + migration for Profile (full toggle) and Deburr (CutMode added, Direction always hidden) — Helix already done | Adaptive operation's direction handling (separate follow-up) |
| Compass wiring for PocketBase, MillFacing, Waterline, Surface, RotarySurface, ThreadMilling | Drilling/Tapping/Probe/Custom (confirmed no change needed — no lateral path) |
| Engrave `Reverse` → `Direction` (CW/CCW) rename, pending open-wire UX call | `isToolSupported` tool-type gating for Deburr (chamfer-only) — reasonable follow-up, not required for direction correctness |
| Investigating Slot's `ExtendRadius` asymmetry question and whether Vcarve is genuinely rotary-only | |
| Task panel (`.ui`/Gui) wiring for every property touched above, incl. fixing Waterline/Surface's pre-existing `CutMode`-not-on-task-panel gap | Task panel redesign beyond adding/toggling the widgets this epic touches |

## Related Epics

- ImproveAdaptiveOperation.md — Adaptive's direction handling should be
  reconsidered there once this epic's pattern exists.
