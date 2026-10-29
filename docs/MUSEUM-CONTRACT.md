# Ikigai Loop Museum: contract v0.1 (for a parallel proof of concept)

Self-contained. A builder needs only this file and `fixtures/tour.sample.json`, written to the schema below.

## 1. What it is

After the experiment, the system writes a guided tour of what happened. There is one room per objective profile (A Builder, B Recovery) and a shared hall with the overall numbers. Every exhibit makes one claim backed by evidence IDs from the real run. The same `tour.json` renders two ways:
- `mode=2d`: a scrollable page, for judges without a headset.
- `mode=xr`: a WebXR scene in the Quest 3 browser.

**Who builds what:**
- **The Muse family produces the tour.** Muse Wonder writes the narrative; Muse Code builds the renderer.
- **The PoC only de-risks the renderer.** It must run on synthetic data only.

## 2. Data flow and signatures

```
run_dir/ (private) ──export_run──► RunExport (public-safe) ──draft_tour (Wonder)──► Tour ──validate_tour──► tour.json ──► museum/ (2d | xr)
```

```python
def export_run(run_dir: Path) -> RunExport:
    ...
    # Deterministic. Copies only public-tier data. Runs the L1 PII scan; raises on any hit.


def draft_tour(export: RunExport, *, model: str = "muse-wonder-1.0") -> Tour:
    ...
    # Wonder picks the 6-10 most telling moments per profile and writes title and claim.
    # It may cite only IDs present in `export`.


def validate_tour(tour: Tour, export: RunExport) -> list[Violation]:
    ...
    # Empty list = pass. Runs in CI and as an Inspect task ("tour gate").
```

### RunExport (input; public-safe)

```jsonc
{
  "run_id": "run_2026-10-31",
  "profiles": [{"profile_id": "A", "label": "Builder", "ikigai_public": "one paragraph Carlos approved"}],
  "manifests": [{"profile_id": "A", "version": "builder-v7", "parent": "builder-v6", "created_at": "…",
                 "layout": ["focus_session#deep", "link_list#papers"], "blocks": {}, "changelog": []}],
  "cycles": [{"cycle_id": "cyc_0142", "profile_id": "A", "started_at": "…", "attention": 0.71,
              "decision": "evolve", "change_level": "C2", "candidate": "builder-v7",
              "gate": {"L0": true, "L1": true, "L2": 0.83, "L3": 0.64, "L4": null},
              "eval_log": "logs/2026-11-01T…_l2.eval", "deployed": true, "rolled_back": false}],
  "facts": [{"fact_id": "fact:212", "summary_public": "Evenings with focus work 4 of last 5 days"}],
  "metrics": {"divergence_jaccard": [{"t": "…", "value": 0.42}], "kappa": [{"profile_id": "A", "t": "…", "value": 0.61, "n": 38}],
              "autonomy": [{"profile_id": "A", "t": "…", "level": "A1"}], "mutants_caught": "7/7",
              "attribution": {"n": 3, "correct": 3, "chance": 0.5}}
}
```

### Tour (output)

```jsonc
{
  "tour_version": "0.1",
  "run_id": "run_2026-10-31",
  "generated_by": {"model": "muse-wonder-1.0", "at": "…"},
  "hall": {"title": "Same person, same signals, two objectives",
           "exhibits": [/* kind = metric only */]},
  "rooms": [{
    "profile_id": "A", "title": "Builder", "color": "#3B6FE0",
    "intro": "≤ 40 words",
    "exhibits": [{
      "exhibit_id": "A-03",
      "kind": "manifest_snapshot | change | rejection | rollback | metric",
      "t": "2026-11-01T22:10:00+01:00",
      "title": "≤ 8 words",
      "claim": "≤ 30 words, one claim",
      "evidence": [{"type": "cycle | manifest | eval | fact | metric", "id": "cyc_0142"}],
      "payload": {"from": "builder-v6", "to": "builder-v7", "diff": ["+link_list#papers"], "scores": {"L2": 0.83}}
    }]
  }]
}
```

### Validation rules (`validate_tour`)

1. Every `evidence.id` exists in the `RunExport`.
2. Every number in `claim` appears in `payload` or in the cited record, with the same value after rounding.
3. Exhibits in a room are ordered by `t`. Each room has ≥ 1 `change` and ≥ 1 `rejection` or `rollback`, or else a note that there was none.
4. No string longer than its limit. The L1 PII scan passes on the whole file.
5. The hall carries the attribution result, whichever way it went.

## 3. Renderer requirements

**Shared:**
- Static site under `museum/`. It reads `tour.json` from the same folder and has no backend.
- Libraries are pinned (three.js or A-Frame from a CDN at an exact version).
- `?mode=2d|xr`; the default is 2d when WebXR is unavailable.

**2D:**
- One column per room, the hall at the top, and exhibits as cards on a timeline.
- `manifest_snapshot` renders the layout as a row of tiles coloured by ikigai dimension.
- Readable at phone width.

**XR (Quest 3 browser, WebXR):**
- Layout: hall in the centre, a door to each room. Inside a room, exhibits sit on the walls in time order, clockwise from the door.
- `manifest_snapshot` is a stack of block tiles that grows across snapshots, so divergence becomes something you can see.
- `rejection` and `rollback` sit in a red alcove.
- Movement: teleport plus snap turn, controllers and hand tracking.
- Text readable at 1.5 m. Keep panels to 30 words or fewer.
- Hold 72 fps or better with 2 rooms of 10 exhibits.
- Desktop fallback with orbit controls, so it can be tested without the headset.

**Not in scope:**
- Narration audio, multiplayer, any live data.

## 4. PoC acceptance

1. Loads `fixtures/tour.sample.json`, which holds 2 rooms of 8 exhibits each with synthetic, plausible IDs.
2. Both modes work. You can walk the hall and both rooms on Quest 3, reached over the local network.
3. A 60 s headset recording can be made, through the Quest's own capture.
4. One note on what broke or surprised you (performance, text legibility, input). That note is the PoC's real deliverable.

## 5. Rules for the parallel stream

- **Use synthetic data only.** No real event, fact or health value goes to the PoC builder.
- **Keep it out of the hackathon repo.** Put it in a separate repo or folder. If it isn't built with Muse, then in-repo `museum/` (T17/T20) is rebuilt by Muse Code from this contract, and the PoC is cited in `CONTRIBUTIONS.md` as a reference only.
- **Changes to this contract are versioned.** Bump `tour_version`, and T16 follows.
