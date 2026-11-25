# agency-nm.com

Static site for NM Agency — Paris-based performance influencer & growth marketing.
Published in **English, French, Italian and German**.

## Structure

| Path | What it is |
|---|---|
| `src/site.html` | The one master document for the single-page app (home, services, work, about, contact, blog). Everything that varies by page or language is an `@@PLACEHOLDER@@`. |
| `src/pages/` | The plain static pages: the eight case studies and the two Partnership Ads pages. |
| `src/assets/media.js` | Brand logos, creator stills and team photos as base64. |
| `i18n/<lang>/*.json` | Translations, as `{english source string: translation}`. Split by area (site, cases, faq, posts, meta, pages) purely for readability — the build merges them. |
| `i18n/keep.json` | Strings that deliberately stay English: brand and people names, platform names, email domains, CSS selectors, bare markup fragments. |
| `build.py` | Generates every page in every language, plus `sitemap.xml`, `robots.txt` and `assets/media.js`. |
| everything else at the root | **Generated.** Don't edit by hand — your change will be overwritten on the next build. |

## Rebuild

```sh
python3 build.py
```

Writes 88 HTML files: 22 pages × 4 languages. Check translation coverage with:

```sh
python3 build.py --check
```

It reports, per language, how many strings are translated and names any that are
missing, any catalogue key that no longer appears in the source (stale), and any
key that is in both a catalogue and `keep.json`. It exits non-zero if anything is
missing, so it works as a pre-commit gate.

To see the full list of translatable strings as a catalogue template:

```sh
python3 build.py --strings
```

## How the languages work

- English lives at the paths it always had (`/`, `/services`, `/work`, …).
  Each other language is a prefix: `/fr/services`, `/it/work`, `/de/blog/...`.
- Every page is a **real pre-rendered file** with its own translated `<title>`,
  description, canonical URL and body — nothing is switched client-side, so each
  language is indexable on its own.
- Every page carries the full reciprocal `hreflang` set (all four languages, plus
  `x-default` → English) and lists itself among its own alternates.
- The language menu in the header is four plain `<a>` links inside a
  `<details>`, so it works without JavaScript and points at the *same page* in
  each language rather than at the homepage.
- Page `<title>` and description are not configured separately: `build.py` reads
  them from the master's own `TITLES` / `DESCS` / `POSTS` data and passes them
  through the same catalogue as the body, so a page's head can never drift from
  what the page shows.

### Changing copy

Edit the English in `src/`, run `python3 build.py --check`, add the new strings to
each `i18n/<lang>/*.json` (or to `i18n/keep.json` if the string should stay
English), then `python3 build.py`.

Translations are matched by **exact source string**. A short string therefore
translates the same way everywhere it appears, so avoid splitting a phrase across
tags when the word order changes between languages — the two highlighted headings
that do this (`@@H1_HOME@@`, `@@H1_CONTACT@@`) are translated whole, in `build.py`.

## Notes

- Routing is path-based (`/services`) with a `#/` fallback where `pushState` is
  unavailable. `404.html` renders the app shell, so unknown paths still work.
- The 24 client logos, 10 creator stills and 3 team photos live in
  `assets/media.js`, which every page and language share as one cached download.
  Keeping them inline would have meant ~547KB per page across 88 files.
- Brand palette lives in the `:root` block: `--accent` (#2F55DC),
  `--accent-2` (#F3EDAD), `--accent-3` (#E563B1).
- Light and dark themes are both defined; the page follows the visitor's system
  setting.

## Deploy

GitHub Pages serves the repository root of the default branch, with the custom
domain in `CNAME`. Run `python3 build.py`, commit the generated files, and push.
