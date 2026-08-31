# Live Galaxy View

`uv run spacesim2 ui` opens the live MOO-II-style galaxy view (it replaced
the old static 3-pane inspector — see `docs/decision-log.md`, 2026-07-11).

## Directory map

```
spacesim2/ui/live/          shipped renderer
  app.py                    LiveGalaxyApp: window, main loop, event routing
  director.py               real-time → turn pacing + per-frame ship interpolation
  camera.py                 map(0..100) → screen; smooth zoom/pan
  view_model.py             pure read-only adapters over Simulation (no core changes)
  history.py                per-turn price/volume/wellbeing series for the charts
  assets.py                 sprite/font loading; procedural-placeholder fallback
  procgen/                  noise.py, nebula.py (backdrop + starfield), placeholders.py
  entities/                 planet_view.py, ship_view.py
  scenes/                   galaxy_scene.py
  widgets/                  hud.py, chart.py, charts_panel.py, info_panel.py
  assets/                   committed PNGs: planets/ ships/ goods/ fonts/ + ATTRIBUTION.md

tools/assetgen/             offline AI asset pipeline (dev-only, never runs at runtime)
  manifest.yaml             one entry per asset: id, category, provider, prompt, seed, status
  pixellab.py, nanobanana.py  provider clients (PIXELLAB_API_KEY / GEMINI_API_KEY)
  generate.py               manifest → provider → staging/raw/
  postprocess.py            downscale, quantize, alpha-trim, pack sheets
  promote.py                approved staging → ui/live/assets/ + ATTRIBUTION.md
  staging/                  gitignored raw candidates
```

## Art cohesion rule

Cross-provider cohesion is enforced two ways: a shared house-style reference
image + fixed palette passed to both generators (`style_ref` to PixelLab,
reference image to Nano Banana/Gemini), and a **palette-snap** in
`postprocess.py` that quantizes every non-pixel-native output to that shared
palette. This is what makes two different generators look like one game. The
renderer falls back to procedural placeholders for any asset not yet
promoted, so code and art never block each other.
