# agency-nm.com

Static site for NM Agency — Paris-based performance influencer & growth marketing.

## Structure

| Path | What it is |
|---|---|
| `index.html` | The built site. Single file, no dependencies, no build step needed to serve it. |
| `404.html` | Copy of `index.html` so unknown paths still render the site. |
| `src/site.html` | Source fragment (no `<head>`), used to regenerate `index.html`. |
| `build.py` | Wraps `src/site.html` into the full document with meta tags. |
| `.nojekyll` | Tells GitHub Pages to serve files as-is. |

## Notes

- Routing is hash-based (`#/services`, `#/work`, `#/about`, `#/contact`), so no server rewrites are required.
- All 24 client logos are embedded as WebP data URIs — nothing is fetched at runtime except Google Fonts.
- Brand palette lives in the `:root` block: `--accent` (#2F55DC), `--accent-2` (#F3EDAD), `--accent-3` (#E563B1).
- Light and dark themes are both defined; the page follows the visitor's system setting.

## Rebuild

```sh
python3 build.py
```

## Deploy

GitHub Pages serves the repository root of the default branch.
For the custom domain, add a `CNAME` file containing `www.agency-nm.com` and point DNS at GitHub Pages.
