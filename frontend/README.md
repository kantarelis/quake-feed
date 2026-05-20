# quake-feed frontend

React + Vite + TypeScript + Leaflet dashboard for the quake-feed API. Styled
with Tailwind CSS. Talks to the backend via a typed client generated from the
FastAPI OpenAPI spec (added in Epic 7 Task 2).

## Commands (from the repo root)

| Make target             | What it does                                       |
| ----------------------- | -------------------------------------------------- |
| `make frontend-install` | `npm ci` in `frontend/`                            |
| `make frontend-dev`     | Vite dev server (proxied to the backend in Task 2) |
| `make frontend-build`   | Production build to `frontend/dist/`               |
| `make frontend-check`   | ESLint + Prettier check + `tsc --noEmit`           |
| `make frontend-test`    | Vitest (run mode)                                  |

Inside `frontend/` the same actions are available as npm scripts
(`npm run dev` / `build` / `lint` / `format:check` / `typecheck` / `test`).

## Stack

- **Build:** Vite 6, React 19, TypeScript (strict).
- **Styling:** Tailwind CSS v4 via the `@tailwindcss/vite` plugin.
- **Lint/format:** ESLint 9 (flat config, typescript-eslint + react-hooks +
  jsx-a11y) and Prettier.
- **Tests:** Vitest + React Testing Library (jsdom).
