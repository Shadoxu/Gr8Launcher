# Wisc Launcher website

The website lives in `web/`. Its homepage is adapted from the supplied Wisc
Launcher HTML, with the screenshots and icons bundled in `web/assets/images/`.
Supporting pages use the same layout, colors, and fonts. Edit the HTML files
and shared CSS/JavaScript directly; no frontend dependencies are required.

## Deploy from the repository root on Vercel

Import this Git repository and leave **Root Directory** at the repository root
(blank or `.`). The root `vercel.json` sets:

- Framework preset: **Other** (`framework: null`).
- Build command: `npm run build`.
- Output directory: `dist/web`.

The root `package.json` exposes the build command, and root `api/release.mjs`
lets Vercel discover the function implemented in `web/api/release.mjs`.
Do not change the Root Directory to `web` for the normal deployment.
Vercel supplies Node.js; the website build does not install Python, build the
desktop launcher, or need any local `temp/` files.

For a custom domain, set **SITE_URL** to its full origin, such as
`https://launcher.example.com`, and rebuild. Without it, the build uses
`VERCEL_PROJECT_PRODUCTION_URL`, then `VERCEL_URL`. These values populate
canonical URLs, social previews, the sitemap, robots rules, and `llms.txt`.
Local builds fall back to `http://localhost:3000`.

A secondary `web/vercel.json` is included for a direct static-folder import.
That mode serves the source files without the root build, so configure SEO
URLs yourself by replacing `__SITE_URL__` throughout that folder. The root
build is recommended because it does this automatically and excludes API
source from the public static output.

## Local preview

Use Node.js 22 or newer. From the repository root:

```bash
npm run dev
```

Open `http://localhost:3000`. The preview supports clean page URLs, aliases,
the custom 404 page, and the public release API. `npm run build` creates the
static output; `npm run preview` serves an existing build. Change the preview
port with `PORT`, and set `SITE_URL` if canonical URLs should use that port.

## Downloads and public API

`GET /api/release` returns the latest stable GitHub release tag and any Windows
x64 installer, portable ZIP, and checksum assets. Published assets can retain
the `Gr8Launcher` name. The fixed upstream is `wisc-launcher/wisc`; API clients
cannot supply an alternate upstream. Successful metadata is cached on Vercel.
Upstream failures return 503 and retain a GitHub release-page fallback in the
website. GET and HEAD are accepted; other methods return 405.

Installer buttons on the homepage open Downloads. Its links work without
JavaScript by going to the latest GitHub release. JavaScript replaces those
links with exact assets when live metadata is available.

## Guides, tools, and site files

The site includes all requested page categories: launcher, mods, modpacks,
skins, downloads, multiplayer, documentation, help, troubleshooting, about,
terms, privacy, cookies/storage, refunds, licenses, a page directory, performance guidance, and
403/404/429/500/502/503 error documents. Vercel uses `404.html` for missing
static resources. The other error documents can be linked or used by a
hosting integration; they do not replace Vercel's own platform error screens.

The `doctor.html` page provides a static launch checklist. `benchmarks.html`
provides Java, memory, and measurement guidance without presenting unverified
performance results. The requested sample `cubeon-bench` path redirects to
that performance guide. No benchmark application is added or advertised.
The guides reflect current repository behavior: offline usernames and Ely.by
accounts, Ely.by sign-in to unlock skin customization, Windows x64 packages,
and the existing mod and modpack installation flows.

`robots.txt`, `sitemap.xml`, `llms.txt`, `favicon.ico`, `_redirects`, and both
Vercel configurations are included. The `_redirects` file is for compatible
static hosts; Vercel uses its JSON redirects. `indexnow-key.txt` and the matching
key-named text file provide an IndexNow ownership key. Publishing these files
does not submit URLs automatically: once the domain is live, use the key in
an IndexNow submission with its public key-file URL.

Source HTML contains `__SITE_URL__` placeholders; deploy the generated output
for correct production metadata. Existing launcher font notices and the GPL
license are preserved in `web/assets/licenses/`. Minecraftia is bundled in
`web/assets/fonts/`, with its attribution, embedded license notice, and original
readme retained in `web/assets/licenses/`. The site makes no Google Fonts requests.

Local validation scripts and screenshots belong in ignored `temp/`. They are
not included in a clone or required for deployment.
