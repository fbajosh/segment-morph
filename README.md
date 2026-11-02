# Segment Morph Studio

A browser-local editor that morphs uploaded SVG line drawings in a configurable, automatically repeating sequence. Each step has independently adjustable movement and hold durations. Export animated SVG, standalone HTML, single SVG frames, or JSON projects. Export FPS and stroke color/weight overrides are configurable.

## Privacy and architecture

Uploaded artwork and projects are **not transmitted to any server**. The site serves static assets; a browser Web Worker runs the Python geometry planner using Pyodide WebAssembly. All geometry calculations and exports occur in the user's browser. A pinned Pyodide runtime and open-source dependencies are downloaded from jsDelivr when the engine initializes. Requests to this CDN do not contain uploaded artwork or project data.

SVG parsing is restricted to supported vector line geometry. Untrusted SVG input is parsed by the geometry engine, not injected as HTML.

## Run locally

```sh
cd public && python3 -m http.server 8775 --bind 127.0.0.1
# Open http://127.0.0.1:8775/
```

## Cloudflare Workers deployment

The project is a static-asset Worker with a small routing script in `src/worker.js`. It **does not use** `assets.base_path` (which requires an account-side feature flag). Cloudflare's `ASSETS` binding serves assets from `public/`; the Worker strips the application path prefix before fetching them.

Deploy from the GitHub-connected Cloudflare Worker or locally with:

```sh
npm install
npm run check
npm run deploy
```

The repository intentionally contains **no production hostname or custom route**. In the Cloudflare dashboard, add a Worker route for `your-domain.example/segment-morph*` to the deployed Worker (the hostname must be a proxied zone in your account). Use an equivalent more restrictive route if desired. The app automatically redirects `/segment-morph` to `/segment-morph/`. For initial testing, the Worker also serves the app from the root of its assigned `workers.dev` hostname.

The `/segment-morph` path is a public URL prefix, not a credential. Changing the application path requires adjusting `APP_PATH` in `src/worker.js` and the corresponding dashboard route. It does not require changing any hostname in source control.

Note: If existing Workers or routing rules already serve a matching path on your domain, review route precedence before assigning this Worker.

## Project compatibility

Projects with `schema_version` 6, 7, or 8 load in v0.9.1. Missing FPS defaults to 60; missing appearance overrides default to disabled. Project files can store original uploaded SVG text and calculated animation data, but no private files are bundled in this repository.

## Limitations

The graph matching and higher-dimensional unfolding are heuristic. Some intermediate frames may contain crossing edges or busy geometry. Exported SVG uses sampled frames at a configurable FPS, while standalone HTML interpolates during `requestAnimationFrame`.
