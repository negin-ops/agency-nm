#!/usr/bin/env python3
"""Build www.agency-nm.com in English, French, Italian and German.

    python3 build.py            # write every page, every language
    python3 build.py --strings  # dump the translatable strings (catalogue template)
    python3 build.py --check    # report untranslated strings per language

Input
    src/site.html        one master document for the whole single-page app, with
                         @@PLACEHOLDERS@@ for everything that varies by page and
                         by language
    src/assets/media.js  brand logos, creator stills and team photos as base64,
                         split out so all pages share one cached download
    i18n/<lang>/*.json   {english source string: translation}, split by area
    i18n/keep.json       strings that stay English on purpose

Page <title> and description are not configured separately: they are read from
the master's own TITLES / DESCS / POSTS data and passed through the same
catalogue as the body, so a page's head can never say something different from
what the page shows.

Output
    /                    English pages at the paths they have today
    /fr /it /de          the same tree per language
    assets/media.js, sitemap.xml, robots.txt

Every page is a real file with its own <title>, description, canonical,
reciprocal hreflang set and translated body, so each language is indexable on
its own rather than switched client-side.
"""
import json
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
ORIGIN = 'https://www.agency-nm.com'

LANGS = ['en', 'fr', 'it', 'de']
LANG_NAMES = {'en': 'English', 'fr': 'Français', 'it': 'Italiano', 'de': 'Deutsch'}
HTML_LANG = {'en': 'en', 'fr': 'fr', 'it': 'it', 'de': 'de'}
OG_LOCALE = {'en': 'en_GB', 'fr': 'fr_FR', 'it': 'it_IT', 'de': 'de_DE'}

# Routes of the single-page app. slug=None means the route's own index page.
ROUTES = ['home', 'services', 'work', 'about', 'contact', 'blog']
POST_SLUGS = [
    'creator-led-growth-dtc-playbook-2026',
    'meta-andromeda-engine-paid-ads',
    'instagram-shoppable-creator-content',
    'youtube-performance-influencer-marketing',
    'marketing-funnel-is-broken',
]
CASE_LASTMOD = '2026-10-22'   # the date the case-study pages were last revised
CASE_PAGES = ['Forward-College', 'Cuure', 'Radical-Storage', 'Faircado',
              'Ubigi', 'Manucurist-Paris', 'Jetpac', 'Sova']

# Plain static pages (no router): the case studies and the Partnership Ads
# landing pages. Each is localised in place and written under /<lang>/.
STANDALONE = ['NMcasestudies/%s.html' % n for n in sorted(CASE_PAGES)] + [
    'services/partnership-ads/index.html',
    'services/partnership-ads/services-performance-influencer-marketing.html',
]

# Root-relative URLs that are assets, not pages: never given a language prefix.
ASSET_PREFIXES = ('/assets/', '/favicon', '/apple-touch-icon', '/og.png',
                  '/icon-512', '/site.webmanifest', '/robots.txt', '/sitemap.xml')


# --------------------------------------------------------------------------
# document scanning
#
# One pass over the document yields every place a human-readable string can
# live: HTML text nodes, a short allowlist of attributes, and JS string
# literals. The same scanner drives --strings, --check and the build, so a
# catalogue key can never drift from what the builder looks up.
# --------------------------------------------------------------------------

ATTRS = ('alt', 'aria-label', 'placeholder')
_TAG = re.compile(r'<[^>]*>')
_ATTR = re.compile(r'\b(' + '|'.join(ATTRS) + r')\s*=\s*(["\'])(.*?)\2', re.S)
_JSSTR = re.compile(r'''(?<![\\\w])(["'])((?:\\.|(?!\1)[^\\\n])*)\1''')
_B64 = re.compile(r'^[A-Za-z0-9+/=]{40,}$')

_JS_UNESCAPE = {'n': '\n', 't': '\t', 'r': '\r', 'b': '\b', 'f': '\f',
                'v': '\v', '0': '\0', '\\': '\\', '"': '"', "'": "'", '\n': ''}


def js_unescape(raw):
    out, i = [], 0
    while i < len(raw):
        c = raw[i]
        if c != '\\':
            out.append(c)
            i += 1
            continue
        nxt = raw[i + 1] if i + 1 < len(raw) else ''
        if nxt == 'u' and re.match(r'[0-9a-fA-F]{4}', raw[i + 2:i + 6]):
            out.append(chr(int(raw[i + 2:i + 6], 16)))
            i += 6
        elif nxt == 'x' and re.match(r'[0-9a-fA-F]{2}', raw[i + 2:i + 4]):
            out.append(chr(int(raw[i + 2:i + 4], 16)))
            i += 4
        elif nxt in _JS_UNESCAPE:
            out.append(_JS_UNESCAPE[nxt])
            i += 2
        else:
            out.append(nxt)
            i += 2
    return ''.join(out)


def js_escape(text, quote):
    out = []
    for ch in text:
        if ch == '\\':
            out.append('\\\\')
        elif ch == quote:
            out.append('\\' + quote)
        elif ch == '\n':
            out.append('\\n')
        elif ch == '\r':
            out.append('\\r')
        elif ch == '\t':
            out.append('\\t')
        elif ord(ch) < 0x20:
            out.append('\\u%04x' % ord(ch))
        else:
            out.append(ch)
    return ''.join(out)


def regions(src):
    """Split the document into ('html'|'script'|'style'|'raw', start, end) spans.

    The spans tile the whole document with no gaps: 'raw' carries the <script>
    and <style> tags themselves, so reassembling the spans in order reproduces
    the input byte for byte.
    """
    pos, out = 0, []
    for m in re.finditer(r'<(script|style)\b[^>]*>([\s\S]*?)</\1\s*>', src, re.I):
        if m.start() > pos:
            out.append(('html', pos, m.start()))
        open_end = m.start() + src.index('>', m.start()) - m.start() + 1
        close_start = m.start(2) + len(m.group(2))
        out.append(('raw', m.start(), open_end))
        out.append((m.group(1).lower(), open_end, close_start))
        out.append(('raw', close_start, m.end()))
        pos = m.end()
    if pos < len(src):
        out.append(('html', pos, len(src)))
    return out


def walk(src, on_html_text, on_attr, on_js):
    """Rebuild src, passing every translatable slot through a callback.

    Each callback takes the current value and returns the replacement (or the
    value unchanged). Returning the input leaves the document byte-identical.
    """
    out = []
    for kind, a, b in regions(src):
        seg = src[a:b]
        if kind in ('style', 'raw'):
            out.append(seg)
            continue
        if kind == 'script':
            last = 0
            pieces = []
            for m in _JSSTR.finditer(seg):
                quote, raw = m.group(1), m.group(2)
                pieces.append(seg[last:m.start()])
                text = js_unescape(raw)
                if not text.strip() or text.startswith('data:') or _B64.match(text):
                    pieces.append(m.group(0))
                else:
                    new = on_js(text)
                    pieces.append(quote + (raw if new == text else js_escape(new, quote)) + quote)
                last = m.end()
            pieces.append(seg[last:])
            out.append(''.join(pieces))
            continue
        # html
        last = 0
        pieces = []
        for m in _TAG.finditer(seg):
            text = seg[last:m.start()]
            pieces.append(on_html_text(text) if text.strip() else text)
            tag = m.group(0)
            if not tag.startswith('</'):
                tlast = 0
                tp = []
                for am in _ATTR.finditer(tag):
                    val = am.group(3)
                    tp.append(tag[tlast:am.start(3)])
                    tp.append(on_attr(val) if val.strip() else val)
                    tlast = am.end(3)
                tp.append(tag[tlast:])
                tag = ''.join(tp)
            pieces.append(tag)
            last = m.end()
        tail = seg[last:]
        pieces.append(on_html_text(tail) if tail.strip() else tail)
        out.append(''.join(pieces))
    return ''.join(out)


_WORD = re.compile(r'[A-Za-z\u00c0-\u024f]{3,}')


def is_prose(s):
    """True when a scanned slot is copy a translator should see.

    Filters machinery (selectors, ids, urls, bare markup) without filtering
    markup that *contains* copy, e.g. '<b>SEO:</b> new landing pages…'.
    """
    s = s.strip()
    if not s or len(s) > 40000:
        return False
    if s.startswith(('data:', 'http:', 'https:', 'mailto:', '--', '@', '#', '.', '/')):
        return False
    if _B64.match(s):
        return False
    # text outside tags / entities only
    bare = re.sub(r'<[^>]*>', ' ', s)
    bare = re.sub(r'&[a-zA-Z]+;|&#\d+;', ' ', bare)
    if not _WORD.search(bare):
        return False
    # a lone lowercase or CONSTANT token is an id, not a sentence
    if re.fullmatch(r'[a-z][a-z0-9_-]*|[A-Z][A-Z0-9_]*', s):
        return False
    if re.fullmatch(r'[\w.]+\([^)]*\)', s):
        return False
    return True


def scan(src):
    """Every distinct prose string in the document, in document order."""
    found = []
    seen = set()

    def note(v):
        t = v.strip()
        if is_prose(t) and t not in seen:
            seen.add(t)
            found.append(t)
        return v

    walk(src, note, note, note)
    return found


def translate(src, catalog):
    """Return src with every prose slot replaced from catalog, where present."""
    stats = {'hit': 0, 'miss': 0}

    def sub(v):
        lead = v[:len(v) - len(v.lstrip())]
        trail = v[len(v.rstrip()):]
        core = v.strip()
        if not is_prose(core):
            return v
        if core in catalog and catalog[core]:
            stats['hit'] += 1
            return lead + catalog[core] + trail
        stats['miss'] += 1
        return v

    return walk(src, sub, sub, sub), stats


# --------------------------------------------------------------------------
# language prefixing of internal links
# --------------------------------------------------------------------------

def is_page_path(path):
    return path.startswith('/') and not path.startswith('//') \
        and not path.startswith(ASSET_PREFIXES)


def prefix_links(src, lang):
    """Point every internal link at the current language's copy of the page."""
    if lang == 'en':
        return src
    pre = '/' + lang

    def fix(path):
        if not is_page_path(path):
            return path
        return pre + ('/' if path == '/' else path)

    out = []
    for kind, a, b in regions(src):
        seg = src[a:b]
        if kind in ('style', 'raw'):
            out.append(seg)
        elif kind == 'script':
            # Only href="/…" / action="/…" written inside a template fragment.
            # Bare path literals are deliberately left alone: "/" and "/" + name
            # appear throughout the router itself, and rewriting those corrupts
            # it. A bare path that really is a link base goes through LPATH() in
            # src/site.html instead.
            def js_fix(m):
                quote, raw = m.group(1), m.group(2)
                if raw.startswith('data:') or _B64.match(raw):
                    return m.group(0)
                new = re.sub(r'((?:href|action)=\\?["\'])(/[\w/\-.]*)',
                             lambda h: h.group(1) + fix(h.group(2)), raw)
                return quote + new + quote
            out.append(_JSSTR.sub(js_fix, seg))
        else:
            out.append(re.sub(r'\b(href|action)=(["\'])(/[^"\']*)\2',
                              lambda m: '%s=%s%s%s' % (m.group(1), m.group(2),
                                                       fix(m.group(3)), m.group(2)),
                              seg))
    return ''.join(out)


# --------------------------------------------------------------------------
# head blocks
# --------------------------------------------------------------------------

def page_path(lang, route, slug=None):
    """The URL path of one page, e.g. ('fr','blog','x') -> /fr/blog/x"""
    pre = '' if lang == 'en' else '/' + lang
    if route == 'home':
        return (pre + '/') if pre else '/'
    p = pre + '/' + route
    return p + '/' + slug if slug else p


def hreflang_block(route, slug=None):
    out = []
    for lg in LANGS:
        out.append('<link rel="alternate" hreflang="%s" href="%s%s">'
                   % (lg, ORIGIN, page_path(lg, route, slug)))
    out.append('<link rel="alternate" hreflang="x-default" href="%s%s">'
               % (ORIGIN, page_path('en', route, slug)))
    return '\n'.join(out)


def og_locale_block(lang):
    out = ['<meta property="og:locale" content="%s">' % OG_LOCALE[lang]]
    for lg in LANGS:
        if lg != lang:
            out.append('<meta property="og:locale:alternate" content="%s">' % OG_LOCALE[lg])
    return '\n'.join(out)


def langswitch_block(lang, route, slug=None, href=None):
    """Header language menu: real links to this same page in each language.

    <details>/<summary>, so it opens with no JavaScript and the four links are
    in the markup for crawlers rather than built on click.
    """
    if href is None:
        def href(lg):
            return page_path(lg, route, slug)
    rows = []
    for lg in LANGS:
        cur = ' aria-current="true"' if lg == lang else ''
        rows.append(
            '          <a href="%s" hreflang="%s" lang="%s"%s>'
            '<span>%s</span><span class="code">%s</span></a>'
            % (href(lg), lg, lg, cur, LANG_NAMES[lg], lg.upper()))
    return (
        '      <details class="lang" id="lang">\n'
        '        <summary aria-label="%s" title="%s">'
        '<span>%s</span><span class="car" aria-hidden="true">\u25be</span></summary>\n'
        '        <div class="lang-menu">\n%s\n        </div>\n'
        '      </details>'
        % (T['switcher_label'][lang], T['switcher_label'][lang], lang.upper(), '\n'.join(rows)))


def jsonld_block(lang, desc):
    data = {
        '@context': 'https://schema.org',
        '@type': 'Organization',
        'name': 'NM Agency',
        'legalName': 'RSPR & Co.',
        'url': ORIGIN + page_path(lang, 'home'),
        'description': desc,
        'inLanguage': HTML_LANG[lang],
        'address': {'@type': 'PostalAddress', 'addressLocality': 'Paris', 'addressCountry': 'FR'},
        'email': 'hello@agency-nm.com',
        'logo': ORIGIN + '/icon-512.png',
        'image': ORIGIN + '/og.png',
        'sameAs': ['https://www.instagram.com/nm.marketing.agency/',
                   'https://www.linkedin.com/company/agencynm'],
    }
    return '<script type="application/ld+json">%s</script>' % json.dumps(data, ensure_ascii=False)


# strings the build itself emits (not present in src/site.html)
T = {
    'switcher_label': {
        'en': 'Choose a language — current: English',
        'fr': 'Choisir une langue — actuelle : français',
        'it': 'Scegli una lingua — attuale: italiano',
        'de': 'Sprache wählen — aktuell: Deutsch',
    },
    'og_image_alt': {
        'en': 'NM Agency — Growth Marketing Agency, Paris',
        'fr': 'NM Agency — agence de growth marketing, Paris',
        'it': 'NM Agency — agenzia di growth marketing, Parigi',
        'de': 'NM Agency — Growth-Marketing-Agentur, Paris',
    },
    # Headings whose highlighted word moves in the sentence, so they are
    # translated whole rather than as fragments around the <span>.
    'h1_home': {
        'en': 'Your <span class="hl">Growth Marketing</span> Partner',
        'fr': 'Votre partenaire en <span class="hl">growth marketing</span>',
        'it': 'Il vostro partner di <span class="hl">growth marketing</span>',
        'de': 'Ihr Partner für <span class="hl">Growth Marketing</span>',
    },
    'h1_contact': {
        'en': 'Do you have a <span class="hl">project?</span>',
        'fr': 'Vous avez un <span class="hl">projet&nbsp;?</span>',
        'it': 'Avete un <span class="hl">progetto?</span>',
        'de': 'Haben Sie ein <span class="hl">Projekt?</span>',
    },
}


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------

def render(master, lang, route, slug, title, desc, catalog):
    doc = master
    body, stats = translate(doc, catalog) if lang != 'en' else (doc, {'hit': 0, 'miss': 0})
    body = prefix_links(body, lang)
    canonical = ORIGIN + page_path(lang, route, slug)
    repl = {
        '@@LANG@@': HTML_LANG[lang],
        '@@LOCALE@@': lang,
        # TITLES/DESCS hold plain text; the head needs it entity-escaped. The
        # JSON-LD block below takes the unescaped text, since entities are not
        # decoded inside a <script>.
        '@@TITLE@@': esc(title),
        '@@DESC@@': esc(desc),
        '@@CANONICAL@@': canonical,
        '@@HREFLANG@@': hreflang_block(route, slug),
        '@@OG_LOCALE@@': og_locale_block(lang),
        '@@OG_IMAGE_ALT@@': T['og_image_alt'][lang],
        '@@LANGSWITCH@@': langswitch_block(lang, route, slug),
        '@@JSONLD@@': jsonld_block(lang, desc),
        '@@H1_HOME@@': T['h1_home'][lang],
        '@@H1_CONTACT@@': T['h1_contact'][lang],
    }
    anchor_css = '@media (max-width:960px){\n  .nav{'
    assert anchor_css in body, 'switcher CSS anchor missing in the master'
    body = body.replace(anchor_css, LANGSWITCH_CSS + anchor_css, 1)
    for k, v in repl.items():
        body = body.replace(k, v)
    left = re.findall(r'@@\w+@@', body)
    assert not left, 'unreplaced placeholders: %s' % set(left)
    return body, stats


def write(path, text):
    full = os.path.join(ROOT, path)
    os.makedirs(os.path.dirname(full) or '.', exist_ok=True)
    with open(full, 'w', encoding='utf-8') as fh:
        fh.write(text)


def esc(s):
    return (s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;'))


def js_object(src, name):
    """Read `var NAME = {...}` / `[...]` out of the master as JSON."""
    m = re.search(r'var ' + name + r'\s*=\s*', src)
    i = m.end()
    start, depth = i, 0
    while True:
        c = src[i]
        if c in '[{':
            depth += 1
        elif c in ']}':
            depth -= 1
            if depth == 0:
                break
        i += 1
    return json.loads(src[start:i + 1])


def head_meta(master, catalog):
    """{route: (title, desc)} and {slug: (title, desc)}, translated."""
    def tr(s):
        return catalog.get(s) or s
    titles = js_object(master, 'TITLES')
    descs = js_object(master, 'DESCS')
    posts = js_object(master, 'POSTS')
    site = 'NM Agency'
    routes = {r: (tr(titles[r]), tr(descs[r])) for r in titles}
    per_post = {p['slug']: (tr(p['title']) + ' | ' + site, tr(p['dek'])) for p in posts}
    return routes, per_post


LANGSWITCH_CSS = """/* ---- language switcher ---- */
.lang{position:relative;flex:0 0 auto}
.lang > summary{
  display:flex;align-items:center;gap:6px;cursor:pointer;list-style:none;
  font-family:var(--f-mono);font-size:11px;letter-spacing:.1em;text-transform:uppercase;
  color:var(--ink-2);background:var(--surface);border:1px solid var(--line);
  padding:11px 13px;border-radius:999px;line-height:1;
  transition:color .15s ease,border-color .15s ease;
}
.lang > summary::-webkit-details-marker{display:none}
.lang > summary:hover{color:var(--ink);border-color:var(--line-strong)}
.lang > summary .car{font-size:9px;opacity:.65;transition:transform .15s ease}
.lang[open] > summary .car{transform:rotate(180deg)}
.lang-menu{
  position:absolute;right:0;top:calc(100% + 8px);z-index:70;min-width:168px;
  display:grid;gap:2px;padding:8px;
  background:var(--surface);border:1px solid var(--line);border-radius:var(--r-m);
  box-shadow:0 18px 40px -22px rgba(13,16,20,.45);
}
.lang-menu a{
  display:flex;align-items:center;justify-content:space-between;gap:10px;
  padding:9px 11px;border-radius:8px;text-decoration:none;
  font-size:14px;font-weight:500;color:var(--ink-2);
}
.lang-menu a:hover{background:var(--surface-2);color:var(--ink)}
.lang-menu a[aria-current]{color:var(--ink);background:var(--surface-2);font-weight:600}
.lang-menu a .code{font-family:var(--f-mono);font-size:10px;letter-spacing:.1em;color:var(--muted)}
@media (max-width:960px){
  /* the header row has to hold logo + language + CTA + burger inside 390px,
     and the CTA label is longest in French and German */
  .logo .sub{display:none}
  .lang > summary{padding:10px 11px;gap:0}
  .lang > summary .car{display:none}
}

"""


def flat_path(lang, src_path):
    """Where a standalone page lives for one language, as a URL path."""
    p = '/' + src_path
    p = re.sub(r'/index\.html$', '/', p)
    p = re.sub(r'\.html$', '', p)
    return p if lang == 'en' else '/' + lang + p


def render_standalone(src, src_path, lang, catalog):
    """Localise a plain static page: body, head, hreflang, switcher."""
    orig_title = re.search(r'<title>(.*?)</title>', src, re.S).group(1)
    orig_desc = re.search(r'<meta name="description" content="(.*?)">', src, re.S).group(1)
    title = catalog.get(orig_title) or orig_title
    desc = catalog.get(orig_desc) or orig_desc

    doc = translate(src, catalog)[0] if lang != 'en' else src
    doc = prefix_links(doc, lang)

    # absolute self-references, including the ones inside the JSON-LD blocks
    if lang != 'en':
        doc = re.sub(r'(%s)(/(?!assets/|favicon|apple-touch-icon|og\.png|icon-512|site\.webmanifest))'
                     % re.escape(ORIGIN),
                     lambda m: m.group(1) + '/' + lang + m.group(2), doc)
        doc = doc.replace('"%s"' % ORIGIN, '"%s/%s/"' % (ORIGIN, lang))

    canonical = ORIGIN + flat_path(lang, src_path)
    doc = re.sub(r'<title>.*?</title>', '<title>%s</title>' % esc(title), doc, count=1, flags=re.S)
    for pat, val in (
        (r'<meta name="description" content=".*?">',
         '<meta name="description" content="%s">' % esc(desc)),
        (r'<meta property="og:title" content=".*?">',
         '<meta property="og:title" content="%s">' % esc(title)),
        (r'<meta property="og:description" content=".*?">',
         '<meta property="og:description" content="%s">' % esc(desc)),
        (r'<meta name="twitter:title" content=".*?">',
         '<meta name="twitter:title" content="%s">' % esc(title)),
        (r'<meta name="twitter:description" content=".*?">',
         '<meta name="twitter:description" content="%s">' % esc(desc)),
        (r'<meta property="og:url" content=".*?">',
         '<meta property="og:url" content="%s">' % canonical),
        (r'<meta property="og:image:alt" content=".*?">',
         '<meta property="og:image:alt" content="%s">' % esc(T['og_image_alt'][lang])),
        (r'<meta property="og:locale" content=".*?">', og_locale_block(lang)),
    ):
        doc = re.sub(pat, lambda m, v=val: v, doc, count=1, flags=re.S)

    alts = '\n'.join(
        '<link rel="alternate" hreflang="%s" href="%s%s">' % (lg, ORIGIN, flat_path(lg, src_path))
        for lg in LANGS)
    alts += ('\n<link rel="alternate" hreflang="x-default" href="%s%s">'
             % (ORIGIN, flat_path('en', src_path)))
    doc = re.sub(r'<link rel="canonical" href=".*?">',
                 lambda m: '<link rel="canonical" href="%s">\n%s' % (canonical, alts),
                 doc, count=1, flags=re.S)

    # Switcher. Most static pages share the site masthead, so the same anchors
    # as src/site.html work. The Partnership Ads long-form page has its own
    # layout and only a breadcrumb bar, so it gets a self-contained inline row
    # there instead — same four links either way.
    href = lambda lg: flat_path(lg, src_path)
    anchor_css = '@media (max-width:960px){\n  .nav{'
    anchor = '    <div class="head-cta">\n'
    if anchor_css in doc and anchor in doc:
        doc = doc.replace(anchor_css, LANGSWITCH_CSS + anchor_css, 1)
        doc = doc.replace(anchor, anchor + langswitch_block(lang, None, None, href=href) + '\n', 1)
    else:
        crumb = '</nav>'
        assert crumb in doc, 'no switcher anchor at all in ' + src_path
        links = ' '.join(
            '<a href="%s" hreflang="%s" lang="%s"%s>%s</a>'
            % (href(lg), lg, lg, ' aria-current="true" style="font-weight:600;color:#2F55DC"'
               if lg == lang else '', lg.upper())
            for lg in LANGS)
        row = ('<span style="margin:0 8px">|</span>'
               '<span style="color:#6B7280" aria-label="%s">%s</span>'
               % (esc(T['switcher_label'][lang]), links))
        doc = doc.replace(crumb, row + crumb, 1)

    doc = re.sub(r'<html lang="[^"]*"', '<html lang="%s"' % HTML_LANG[lang], doc, count=1)
    return doc


def load_catalog(lang):
    """Merge every i18n/<lang>/*.json into one {source: translation} map."""
    d = os.path.join(ROOT, 'i18n', lang)
    out = {}
    for name in sorted(os.listdir(d)):
        if not name.endswith('.json'):
            continue
        part = json.load(open(os.path.join(d, name), encoding='utf-8'))
        dupes = set(part) & set(out)
        assert not dupes, 'duplicate keys in i18n/%s: %s' % (lang, list(dupes)[:3])
        out.update(part)
    return out


def main():
    master = open(os.path.join(ROOT, 'src/site.html'), encoding='utf-8').read()

    def all_strings():
        """Every translatable string across the master and the static pages."""
        found, seen = [], set()
        docs = [master] + [open(os.path.join(ROOT, 'src/pages', p), encoding='utf-8').read()
                           for p in STANDALONE]
        for d in docs:
            for s in scan(d):
                if re.fullmatch(r'@@\w+@@', s):
                    continue
                if s not in seen:
                    seen.add(s)
                    found.append(s)
            # <title> and the description live in attributes the scanner skips
            for pat in (r'<title>(.*?)</title>',
                        r'<meta name="description" content="(.*?)">'):
                m = re.search(pat, d, re.S)
                if m and not re.fullmatch(r'@@\w+@@', m.group(1)) and m.group(1) not in seen:
                    seen.add(m.group(1))
                    found.append(m.group(1))
        return found

    if '--strings' in sys.argv:
        print(json.dumps({s: '' for s in all_strings()}, ensure_ascii=False, indent=1))
        return

    catalogs = {'en': {}}
    for lg in LANGS[1:]:
        catalogs[lg] = load_catalog(lg)

    if '--check' in sys.argv:
        found = all_strings()
        # strings that stay English on purpose: brand and people names, email
        # domains, css selectors, bare markup fragments
        keep = set(json.load(open(os.path.join(ROOT, 'i18n/keep.json'), encoding='utf-8')))
        want = [s for s in found if s not in keep]
        bad = 0
        for lg in LANGS[1:]:
            missing = [s for s in want if not catalogs[lg].get(s)]
            print('%s: %d/%d translated, %d kept as-is'
                  % (lg, len(want) - len(missing), len(want), len(keep)))
            for s in missing:
                print('   MISSING %r' % (s[:110],))
            bad += len(missing)
        for lg in LANGS[1:]:
            for k in catalogs[lg]:
                if k not in set(found):
                    print('   STALE  [%s] %r' % (lg, k[:110]))
                    bad += 1
                elif k in keep:
                    print('   KEEP-BUT-TRANSLATED [%s] %r' % (lg, k[:110]))
        for s in keep:
            if s not in set(found):
                print('   STALE-KEEP %r' % (s[:110],))
        sys.exit(1 if bad else 0)

    # assets shared by every page and language
    os.makedirs(os.path.join(ROOT, 'assets'), exist_ok=True)
    shutil.copyfile(os.path.join(ROOT, 'src/assets/media.js'),
                    os.path.join(ROOT, 'assets/media.js'))

    urls = []
    total = {}
    for lang in LANGS:
        cat = catalogs[lang]
        routes, posts = head_meta(master, cat)
        for route in ROUTES:
            title, desc = routes[route]
            html, stats = render(master, lang, route, None, title, desc, cat)
            out = page_path(lang, route)
            write(('index.html' if out == '/' else out.strip('/') + '/index.html'), html)
            urls.append((route, None, 1.0 if route == 'home' else 0.8))
            total[lang] = total.get(lang, 0) + stats['hit']
        for slug in POST_SLUGS:
            title, desc = posts[slug]
            html, _ = render(master, lang, 'blog', slug, title, desc, cat)
            write(page_path(lang, 'blog', slug).strip('/') + '/index.html', html)
            urls.append(('blog', slug, 0.7))
        # 404: served for any unknown path, so it must render the app shell
        title, desc = routes['home']
        html, _ = render(master, lang, 'home', None, title, desc, cat)
        write(('404.html' if lang == 'en' else '%s/404.html' % lang), html)
        # the plain static pages
        for sp in STANDALONE:
            raw = open(os.path.join(ROOT, 'src/pages', sp), encoding='utf-8').read()
            write(sp if lang == 'en' else '%s/%s' % (lang, sp),
                  render_standalone(raw, sp, lang, cat))

    # Sitemap. Every language of every page is listed, and each entry names the
    # full set of alternates (including itself and x-default), which is what
    # Google asks for when the same page exists in several languages.
    post_dates = {p['slug']: p.get('date', '') for p in js_object(master, 'POSTS')}
    entries = []          # (path-for-language, priority, lastmod)
    for route, slug, prio in dict.fromkeys(urls):
        entries.append((lambda lg, r=route, s=slug: page_path(lg, r, s),
                        prio, post_dates.get(slug, '')))
    for name in CASE_PAGES:
        entries.append((lambda lg, n=name: flat_path(lg, 'NMcasestudies/%s.html' % n),
                        0.7, CASE_LASTMOD))
    for sp in ('services/partnership-ads/index.html',
               'services/partnership-ads/services-performance-influencer-marketing.html'):
        entries.append((lambda lg, p=sp: flat_path(lg, p), 0.7, ''))

    rows = []
    for path_of, prio, lastmod in entries:
        alts = ''.join('<xhtml:link rel="alternate" hreflang="%s" href="%s%s"/>'
                       % (lg, ORIGIN, path_of(lg)) for lg in LANGS)
        alts += ('<xhtml:link rel="alternate" hreflang="x-default" href="%s%s"/>'
                 % (ORIGIN, path_of('en')))
        for lang in LANGS:
            rows.append('  <url><loc>%s%s</loc>%s%s<priority>%s</priority></url>'
                        % (ORIGIN, path_of(lang), alts,
                           '<lastmod>%s</lastmod>' % lastmod if lastmod else '', prio))

    write('sitemap.xml',
          '<?xml version="1.0" encoding="UTF-8"?>\n'
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"\n'
          '        xmlns:xhtml="http://www.w3.org/1999/xhtml">\n'
          + '\n'.join(rows) + '\n</urlset>\n')

    write('robots.txt', 'User-agent: *\nAllow: /\n\nSitemap: %s/sitemap.xml\n' % ORIGIN)
    write('.nojekyll', '')

    for lang in LANGS[1:]:
        print('%s: %d strings replaced per page' % (lang, total[lang] // len(ROUTES)))
    print('pages written: %d' % (len(LANGS) * (len(ROUTES) + len(POST_SLUGS) + 1)))


if __name__ == '__main__':
    main()
