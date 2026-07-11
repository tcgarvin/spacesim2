# Plan: Live Galaxy View + AI Pixel-Art Asset Pipeline for SpaceSim2

> Status: **built.** Build steps 1–9 landed (live view, charts, click-to-drill,
> asset pipeline, baked planets + freighter rotations + all 40 goods icons).
> Remaining polish: bundled OFL font, stronger wellbeing overlay on baked
> planets, possible market ticker.

## Context

`spacesim2 ui` today is a **static 3-pane data browser** (`ui/pygame_ui.py` + `ui/components/*` + `ui/renderers/*`, ~3,400 LOC): press Space, read spreadsheet numbers. An inspector, not a spectacle. Meanwhile the core model is begging to be watched live — planets at real `(x,y)` (`core/planet.py:22`), ships with `travel_progress`/`destination`/`cargo`/`status` (`core/ship.py:626-639`), actor drive `health/debt/buffer/urgency`+`get_score()` (`core/drives/actor_drive.py:84-96`), and markets streaming `transaction_history`/`get_avg_price`/`scarcity_pressure_for`.

**Goal:** Replace the inspector with a **living galaxy** you can leave running for the wow factor *and* explore as it runs. Aesthetic = **Master of Orion II galaxy map, higher-res**: detailed worlds on a moody nebula starfield, ships with engine glow, restrained chrome (no cheesy animated HUD).

**Decisions locked with the user:**
- Discard the old inspector entirely; platform = pygame.
- **ProcGen** handles atmospheric/continuous visuals (nebula, parallax starfield, glow, trails, effects).
- **Discrete entities (planets, ships, goods) come from an offline AI pixel-art asset pipeline** — generated, curated, and **committed for long-term reuse**.
- Generators: **PixelLab** (pixel-native; ships + goods icons) + **Nano Banana / Gemini** (painterly planets → downscaled/quantized). No Gamelabs for now.
- Generation is **script-driven with env-var keys** (reproducible, prompts/seeds in a manifest). PixelLab MCP optional later.
- First build = **full pipeline + renderer scaffold (ProcGen placeholders) + a thin proof slice** (1 planet, 1 ship, 3 goods) end-to-end, then mass-generate.

---

## Part A — Offline AI Asset Pipeline (`tools/assetgen/`, dev-only, not shipped)

Tool-agnostic, declarative, human-in-the-loop. Runtime never calls an API — it loads committed PNGs.

```
tools/assetgen/
  manifest.yaml         Single source of truth. One entry per asset:
                        id, category(planet|ship|good), provider(pixellab|nanobanana),
                        kind(object|rotation|painterly), size, frames, prompt,
                        style_ref, seed, status(draft|approved).
  providers/
    pixellab.py         REST client (https://api.pixellab.ai/v2). Uses Create-Image
                        (Pixflux/Bitforge, transparent bg ~$0.008/64px) + Rotate
                        (~$0.011) for ship facings. Auth via PIXELLAB_API_KEY.
    nanobanana.py       google-genai client, model "gemini-2.5-flash-image"
                        (~$0.04/img). Auth via GEMINI_API_KEY.
  generate.py           Read manifest (optionally --id/--category) -> call provider
                        -> write raw to staging/raw/<id>/.
  postprocess.py        For non-pixel-native (Nano Banana): downscale + quantize +
                        PALETTE-SNAP to one shared house palette. All: alpha-trim,
                        normalize size, pack rotation strips / sprite sheets. (Pillow + numpy.)
  contact_sheet.py      Build a PNG grid (or marimo cell) of candidates for review.
  promote.py            Approved staging -> spacesim2/ui/live/assets/<category>/,
                        update assets index json + ATTRIBUTION.md (provider/prompt/seed/license).
  staging/              gitignored: raw + candidates.
  .env.example          PIXELLAB_API_KEY=, GEMINI_API_KEY=   (real .env gitignored)
```

**Cross-provider cohesion** is enforced two ways: a shared **house-style reference image** + fixed **palette** passed as `style_ref` to PixelLab and as a reference to Nano Banana, and a `postprocess` **palette-snap** that quantizes everything to that palette. This is what makes two different generators look like one game.

**Division of labor:** planets → Nano Banana (painterly → quantized, "MOO II but higher-res"); ships → PixelLab Rotate (directional facing as they travel); goods/commodity icons (~15, enumerated from `commodity_registry`) → PixelLab objects (transparent, cheap, style-matched).

---

## Part B — Live Renderer (`spacesim2/ui/live/`, shipped)

Native-resolution, smooth alpha-blended. ProcGen backdrop + baked-asset entities. A loader falls back to **procedural placeholders** when an asset isn't promoted yet, so code and art never block each other.

```
ui/live/
  app.py            LiveGalaxyApp: window, main loop, clock, director, camera,
                    scene stack, event routing.
  director.py       Real-time -> turn pacing (turns/sec, play/pause/speed) +
                    per-frame interpolation of ship progress BETWEEN turns
                    (anti-slideshow: ships glide at 60fps over discrete turns).
  camera.py         map(0..100) -> screen; smooth zoom/pan.
  view_model.py     PURE read-only adapters over Simulation (NO core changes):
                    planet_wellbeing(), population(), wealth(), dominant_cargo(),
                    recent_trades(). Unit-tested.
  assets.py         Load committed sprites from the assets index by id; bundled font;
                    palette + wellbeing->color ramp; procedural-placeholder fallback.
  procgen/
    noise.py        fBm/value-noise (numpy) shared by nebula + placeholders.
    nebula.py       Full-screen nebula backdrop + colored parallax starfield.
    placeholders.py Procedural stand-ins (shaded sphere planet, simple ship/icon)
                    used until baked assets exist.
  entities/
    planet_view.py  Blit baked planet sprite; ProcGen animated atmosphere ring +
                    slow cloud-scroll + subtle bob for life; wellbeing tint/overlay.
    ship_view.py    Baked ship rotation frames facing travel heading; engine-glow
                    trail; cargo tint. Trade lanes brighten with traffic; dock flare.
    good_icon.py    Commodity icons for the ticker/overlay.
  scenes/
    galaxy_scene.py Backdrop, planets, lanes, ships, flares, ticker.
    planet_overlay.py  Drill-down: wellbeing breakdown, top prices, docked ships,
                    recent trades. Esc returns.
  widgets/
    ticker.py       Quiet market readout (price up/down, scarcity highlight, good icons).
    hud.py          Minimal chrome: turn, clock, speed, controls. No blink/scanlines.
  assets/
    planets/ ships/ goods/   committed PNGs + index.json + ATTRIBUTION.md
    <font>.ttf               one bundled OFL font (not a pixel font)
```

**Planet "life" without rotation frames:** Nano Banana won't give clean rotation; instead bake one painterly planet sprite per archetype and animate via a slow-scrolling cloud/atmosphere overlay + subtle bob + wellbeing-tinted glow ring (ProcGen). Ships *do* get real PixelLab rotation frames (cheap, and facing matters as they move). **Controls:** Space play/pause, +/- speed, wheel zoom, drag pan, click planet -> overlay, Esc back/quit.

---

## Dependencies
- Runtime (add explicit): `numpy` (procgen), `pillow` (sprite loading/tinting). Both already transitive.
- Asset pipeline (new optional extra `assetgen`, NOT runtime): `google-genai`, `httpx` (or PixelLab's client), `pillow`. Keeps the shipped app key-free and light.
- `pyproject.toml`: add deps + `[tool.setuptools.package-data]` so committed assets/font ship in the wheel.

## What the user needs to set up (so generation can run)
1. **PixelLab** account → API key. Put `PIXELLAB_API_KEY` in `tools/assetgen/.env` (gitignored). Pay-per-image (~$0.008–0.011 each) or a sub.
2. **Google Gemini** API key (AI Studio) with billing → `GEMINI_API_KEY` in the same `.env`. ~$0.04/image.
3. Confirm a **monthly budget ceiling** for generation (the proof slice is pennies; a full pass is a few dollars).
4. (Optional, later) PixelLab **MCP** token for interactive in-session generation.
Provide `.env.example` + exact run commands; user only pastes keys. No paid generation runs until keys exist and the user gives the go-ahead. Steps 1–7 below need no keys and can proceed first.

## Files deleted (old inspector)
`ui/pygame_ui.py`; `ui/components/*`; `ui/renderers/*`; `ui/utils/input_handler.py`.

## Files reused / salvaged
`ui/utils/colors.py` → palette into `live/assets.py`; `ui/utils/text.py` → font-loading pattern; `ui/headless.py` → keep (used by `run --verbose`).

## Wiring
- `cli/commands/ui.py`: launch `LiveGalaxyApp`; keep `--planets/--actors/--makers/--ships/--no-planet-attributes`; add `--speed`/`--paused`; drop `--auto-turns`. Keep lazy import + `PYGAME_AVAILABLE` guard.

## Verification
1. **pytest (CI-safe):**
   - `test_live_view_model.py` — pure adapters on a small `setup_simple` run: wellbeing excludes market makers, in [0,1]; `dominant_cargo` matches cargo; `recent_trades` windows correctly (tolerances; sim is stochastic).
   - `test_live_render_smoke.py` — `SDL_VIDEODRIVER=dummy`, build app, step director + render ~30 frames over a few turns; assert no exceptions, non-blank frame, placeholder + baked-asset load paths both work.
   - `test_assetgen_pipeline.py` — postprocess/promote on a fixture PNG (palette-snap, alpha-trim, index update) with providers **mocked** (no network/keys in CI).
2. **Dev loop:** `uv run spacesim2 dev check` stays green (ruff/mypy/pytest/short sim); mypy blocking + full annotations.
3. **Manual visual (local):** `uv run spacesim2 ui --planets 5 --actors 50` — watch worlds drift/glow, ships glide lit lanes, famines redden; click to drill in. (No display in agent env; dummy-driver smoke test is the proxy.)
4. **Asset proof:** after keys, `uv run python tools/assetgen/generate.py --id <proof ids>` → review contact sheet → `promote.py` → re-run `ui` and confirm baked sprites replace placeholders.

## Build order
1. Scaffold `live/`; `app.py` + window + loop; wire `cli/commands/ui.py`; delete old inspector.
2. `procgen/noise.py` + `nebula.py` + `camera.py` → nebula backdrop + parallax starfield, pan/zoom.
3. `view_model.py` + `entities/planet_view.py` + `procgen/placeholders.py` → planets (procedural placeholders) with wellbeing tint at map positions.
4. `director.py` + `entities/ship_view.py` → ships gliding between worlds (interpolated) + trade lanes + flares.
5. `widgets/ticker.py` + `hud.py` + `entities/good_icon.py` → restrained chrome + market readout.
6. `scenes/planet_overlay.py` → click-to-drill-down.
7. **Asset pipeline**: `tools/assetgen/` (manifest, providers, generate, postprocess, contact_sheet, promote, .env.example) + `assetgen` extra + package-data.
8. **Thin proof slice** (after keys): generate 1 planet (Nano Banana) + 1 ship (PixelLab rotation) + 3 goods (PixelLab), post-process, promote; confirm they render over placeholders.
9. Bundle font; tests (view_model + render smoke + assetgen w/ mocked providers); `dev check` green. THEN mass-generate the rest.

---

## Provider reference (for the future session)
- **PixelLab**: REST `https://api.pixellab.ai/v2` (docs at `/v2/docs`); also an MCP server at `https://api.pixellab.ai/mcp` (Bearer token, async job IDs ~2–5 min). Create-Image (Pixflux/Bitforge) for transparent objects; Rotate for directional facings. Pay-per-image or subscription (~$9–22/mo).
- **Nano Banana / Gemini**: `pip install google-genai`; `genai.Client(api_key=...)`; `client.models.generate_content(model="gemini-2.5-flash-image", contents=[prompt, ref_image])`. ~$0.04/image; great subject consistency + iterative edits; not pixel-native (post-process to quantize).
