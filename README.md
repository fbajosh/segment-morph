# Segment Morph Studio

A browser-local editor that morphs three uploaded SVG line drawings in a configurable, automatically repeating sequence. Each leg has independently adjustable movement and hold durations. Export animated SVG, standalone HTML, single SVG frame, or a JSON project. SVG export FPS is configurable; stroke color and stroke width may be forced to a uniform value in preview and exports.

## Privacy / architecture

Uploaded artwork and projects are **not transmitted to any server**. The app is served as static files. A dedicated browser Web Worker runs the Python geometry planner using Pyodide WebAssembly; all geometry calculations, preview evaluation and exports occur in the user's browser. A pinned Pyodide runtime and the open-source `networkx` dependency are downloaded from jsDelivr during initialization; those requests contain no artwork or project data. An internet connection is required for initial runtime loading. Pyodide startup may be slow on first visit.

Only SVG line drawings with supported geometric elements are accepted. The drawing parser deliberately rejects scripts, external objects and non-linear geometry. Uploaded SVG text is parsed in Python and never injected into the DOM as HTML.

## Run locally

```sh
cd public && python3 -m http.server 8775 --bind 127.0.0.1
# Open http://127.0.0.1:8775/
```

For the public Cloudflare route, assets are mounted at `/segment-morph/`. There is no application API, user-data storage, analytics, or backend computation.

## Cloudflare Workers deployment

This repository includes a `wrangler.toml` with static assets mounted at `/segment-morph` and a path-scoped Worker route for the `appmogged.com` zone. Wrangler 4.148+ is required for `assets.base_path`.

```sh
npm install
npx wrangler login
npm run deploy
```

The `appmogged.com` domain must be a Cloudflare-managed proxied zone with permission to add a Worker route. Check any existing Worker routes before deployment; path precedence and application availability must be validated on the live zone. This config does not change unrelated site files or routes. No site has been deployed merely by pushing this repository.

## Project compatibility

Projects with `schema_version` 6, 7 or 8 load into v0.9. Missing FPS uses 60, and missing visual override settings default to disabled. Saved v0.9 projects add `export.color_override` and `export.width_override` while retaining existing baked animation frames.

## Limitations

The graph matcher and higher-dimensional unfolding are heuristic. Some intermediate frames can still contain line crossings and visually busy structures. Each transition has a fixed number of motion samples; SVG export re-samples at the requested FPS, while standalone HTML interpolates during `requestAnimationFrame`.
