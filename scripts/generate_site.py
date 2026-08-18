#!/usr/bin/env python3
"""
Generador de sitio estático para Nueva Finanza.

Convierte data/news.json en páginas HTML REALES (contenido presente en el
HTML, no insertado después por JavaScript), para que Google pueda rastrear
e indexar cada artículo, sección y autor sin depender de que se ejecute JS.

Genera:
  /<seccion-slug>/<articulo-slug>/index.html   (artículo individual)
  /<seccion-slug>/index.html                    (listado de sección)
  /autor/<autor-slug>/index.html                (página de autor)
  /index.html                                   (portada, regenerada)
  /sitemap.xml                                  (con las URLs limpias)

Uso:
  python3 scripts/generate_site.py                 -> regenera TODO el sitio
"""

import json
import os
import re
import subprocess
import unicodedata
from datetime import datetime, timezone

SITE_URL = "https://www.nuevafinanza.com"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEWS_PATH = os.path.join(ROOT, "data", "news.json")
# IMPORTANTE: reemplaza esto por tu usuario y el nombre real del repositorio
# de GitHub que vayas a crear para este sitio.
GITHUB_OWNER = "enfoquemundial"
GITHUB_REPO = "nuevafinanza"

SITE_NAME = "Nueva Finanza"
SITE_TAGLINE = "Entiende tus finanzas, sin complicaciones"
SITE_DESCRIPTION = "Nueva Finanza: educación financiera, mercados, inversión y economía explicados de forma clara. Contenido verificado, sin jerga innecesaria."

AUTHOR_BIOS = {
    "Redacción Nueva Finanza": "Equipo editorial de Nueva Finanza, especializado en economía, mercados e inversión.",
    "Carla Espinal": "Redactora de Nueva Finanza, cubre mercados, criptomonedas e inversión personal.",
    "Manuel Objío": "Redactor de Nueva Finanza, especializado en economía global y finanzas corporativas.",
}

# Umbral mínimo de artículos para que una página de sección/autor se deje
# indexable. Por debajo de esto, se marca noindex y se excluye del sitemap
# (una página con 1 solo artículo se ve como contenido pobre para Google).
MIN_ARTICLES_CATEGORY_INDEXABLE = 3
MIN_ARTICLES_AUTHOR_INDEXABLE = 2

# Marcadores de contenido de plantilla / relleno que NUNCA deben llegar a publicarse
TEMPLATE_MARKERS = [
    "Título\n", "\nTítulo\n", "Categoría\n", "\nCategoría\n",
    "Desarrollo de la noticia", "no inventada",
    "Escribe aquí", "Lorem ipsum", "PLACEHOLDER", "[PLACEHOLDER]", "TODO:",
]

VALID_CATEGORIES = {"Mercados", "Criptomonedas", "Economía", "Finanzas Personales",
                     "Empresas", "Inversión"}


class ArticleValidationError(Exception):
    pass



def validate_article(n):
    """Valida los requisitos mínimos antes de generar/publicar un artículo.
    Lanza ArticleValidationError con el motivo si algo no cumple — el llamador
    decide si eso significa abortar la publicación (auto_publish.py) o solo
    saltarse ese artículo al reconstruir todo el sitio (build_all)."""
    if not n.get("title", "").strip():
        raise ArticleValidationError(f"id={n.get('id')}: título vacío")
    if not n.get("content", "").strip():
        raise ArticleValidationError(f"id={n.get('id')}: contenido vacío")
    if len(n.get("content", "").split()) < 100:
        raise ArticleValidationError(f"id={n.get('id')}: contenido demasiado corto (<100 palabras)")
    if n.get("category") not in VALID_CATEGORIES:
        raise ArticleValidationError(f"id={n.get('id')}: categoría inválida '{n.get('category')}'")
    if not n.get("author", "").strip():
        raise ArticleValidationError(f"id={n.get('id')}: autor vacío")
    if not n.get("date"):
        raise ArticleValidationError(f"id={n.get('id')}: fecha vacía")
    try:
        datetime.fromisoformat(n["date"].replace("Z", "+00:00"))
    except Exception:
        raise ArticleValidationError(f"id={n.get('id')}: fecha inválida '{n.get('date')}'")
    images = n.get("images", [])
    if not images or not isinstance(images, list) or not images[0].strip():
        raise ArticleValidationError(f"id={n.get('id')}: sin imagen válida")
    if not str(n.get("id", "")).strip():
        raise ArticleValidationError("artículo sin id")
    for marker in TEMPLATE_MARKERS:
        if marker in n["title"] or marker in n["content"]:
            raise ArticleValidationError(
                f"id={n.get('id')}: contiene texto de plantilla ('{marker.strip()}') — no se publica"
            )
    return True


def slugify(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    text = re.sub(r"-{2,}", "-", text)
    return text or "articulo"


def category_slug(category):
    return slugify(category)


def load_news():
    with open(NEWS_PATH, encoding="utf-8") as f:
        return json.load(f)


# --- Fragmentos de plantilla compartidos (mismo diseño/branding actual) ---

def head(title, description, canonical_url, og_type="website", og_image="", extra_ld="", noindex=False):
    og_image_tag = f'\n    <meta property="og:image" content="{og_image}">' if og_image else ""
    robots = "noindex, follow" if noindex else "index, follow"
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="icon" type="image/svg+xml" href="{rel(canonical_url)}logo/logo.svg">
    <title>{title}</title>
    <meta name="description" content="{description}">
    <meta name="robots" content="{robots}">
    <meta property="og:title" content="{title}">
    <meta property="og:description" content="{description}">
    <meta property="og:type" content="{og_type}">
    <meta property="og:locale" content="es_DO">
    <meta property="og:url" content="{canonical_url}">{og_image_tag}
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="{title}">
    <meta name="twitter:description" content="{description}">
    <link rel="canonical" href="{canonical_url}">
    {extra_ld}
    <!-- Consentimiento de cookies: por defecto todo denegado hasta que el
         visitante elija — Google Consent Mode. Debe ir ANTES de cargar gtag. -->
    <script>
        window.dataLayer = window.dataLayer || [];
        function gtag(){{dataLayer.push(arguments);}}
        gtag("consent", "default", {{
            "ad_storage": "denied",
            "analytics_storage": "denied",
            "ad_user_data": "denied",
            "ad_personalization": "denied"
        }});
    </script>
    <!-- Google tag (gtag.js) — ID de Google Analytics de Nueva Finanza -->
    <script async src="https://www.googletagmanager.com/gtag/js?id=G-VD1W8XVLVH"></script>
    <script>
        gtag("js", new Date());
        gtag("config", "G-VD1W8XVLVH");
    </script>

    <link rel="stylesheet" href="{rel(canonical_url)}css/tailwind.min.css">
    <link href="https://fonts.googleapis.com/css2?family=Sora:wght@600;700;800&family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <script src="https://unpkg.com/lucide@latest" defer></script>
    <style>
        body {{ font-family: 'Inter', sans-serif; }}
        .font-display {{ font-family: 'Sora', sans-serif; }}
        .logo-nav img {{ height: 44px; width: auto; }}
    </style>
</head>
<body class="bg-white text-slate-900">
<div class="h-1 bg-emerald-600"></div>
"""


def rel(canonical_url):
    """Cuántos niveles hay que subir (../) según la profundidad de la URL, para enlazar bien css/logo."""
    path = canonical_url.replace(SITE_URL, "").strip("/")
    if not path:
        return ""
    depth = path.count("/") + 1
    return "../" * depth


CATEGORY_DISPLAY_NAMES = {
    "Mercados": "Mercados",
    "Criptomonedas": "Criptomonedas",
    "Economía": "Economía",
    "Finanzas Personales": "Finanzas Personales",
    "Empresas": "Empresas",
    "Inversión": "Inversión",
}


def nav(canonical_url, news=None):
    home = rel(canonical_url) + "index.html" if rel(canonical_url) else "index.html"
    login = rel(canonical_url) + "admin/login/index.html" if rel(canonical_url) else "admin/login/index.html"
    buscar = rel(canonical_url) + "buscar/index.html" if rel(canonical_url) else "buscar/index.html"

    cat_links = ""
    if news:
        cats = sorted(set(a["category"] for a in news))
        last_date = {c: max(a["date"] for a in news if a["category"] == c) for c in cats}
        cats.sort(key=lambda c: last_date[c], reverse=True)
        cat_links = "".join(
            f'<a href="{category_url(c)}" class="text-xs font-semibold text-slate-600 hover:text-emerald-700 whitespace-nowrap transition-colors">{esc(CATEGORY_DISPLAY_NAMES.get(c, c))}</a>'
            for c in cats
        )

    return f"""
<nav class="sticky top-0 z-50 bg-white border-b-2 border-emerald-600">
    <div class="max-w-7xl mx-auto px-4">
        <div class="flex items-center justify-between h-16 gap-6">
            <div class="logo-nav cursor-pointer flex-shrink-0" onclick="location.href='{home}'">
                <img src="{rel(canonical_url)}logo/logo.svg" alt="{SITE_NAME}">
            </div>
            <div class="hidden md:flex items-center gap-5 overflow-x-auto no-scrollbar flex-1">
                {cat_links}
            </div>
            <div class="flex items-center gap-4 flex-shrink-0">
                <button onclick="location.href='{buscar}'" class="text-slate-500 hover:text-emerald-700 transition-colors" aria-label="Buscar">
                    <i data-lucide="search" class="w-5 h-5"></i>
                </button>
                <button onclick="location.href='{login}'" class="text-slate-400 hover:text-emerald-700 transition-colors" aria-label="Acceso">
                    <i data-lucide="circle-user" class="w-5 h-5"></i>
                </button>
            </div>
        </div>
        <div class="md:hidden flex items-center gap-5 overflow-x-auto no-scrollbar pb-3">
            {cat_links}
        </div>
    </div>
</nav>
<style>.no-scrollbar::-webkit-scrollbar {{ display: none; }} .no-scrollbar {{ -ms-overflow-style: none; scrollbar-width: none; }}</style>
"""


def breadcrumbs(items, canonical_url):
    """items: lista de (nombre, url_absoluta_o_None_si_actual)"""
    parts = []
    for name, url in items:
        if url:
            parts.append(f'<a href="{url}" class="hover:text-emerald-600">{esc(name)}</a>')
        else:
            parts.append(f'<span class="text-slate-800 font-medium">{esc(name)}</span>')
    html = " <span class='mx-1 text-slate-300'>/</span> ".join(parts)
    return f'<nav class="max-w-7xl mx-auto px-4 pt-6 text-xs text-slate-400">{html}</nav>'


def breadcrumb_ld(items):
    els = []
    for i, (name, url) in enumerate(items, start=1):
        item = {"@type": "ListItem", "position": i, "name": name}
        if url:
            item["item"] = url
        els.append(item)
    return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": els}


def footer(canonical_url):
    r = rel(canonical_url)
    return f"""
<footer class="bg-slate-900 text-slate-300 mt-20">
    <div class="max-w-6xl mx-auto px-4 py-12">
        <div class="flex flex-col md:flex-row md:items-start md:justify-between gap-8 pb-10 border-b border-slate-800">
            <div class="max-w-sm">
                <img src="{r}logo/logo.svg" class="h-7 mb-4 brightness-0 invert opacity-90" alt="{SITE_NAME}">
                <p class="text-sm text-slate-400 leading-relaxed">{SITE_DESCRIPTION}</p>
            </div>
            <div class="flex gap-12">
                <ul class="space-y-2 text-sm">
                    <li><a href="{r}index.html" class="hover:text-white transition-colors">Inicio</a></li>
                    <li><a href="{r}sobre-nosotros.html" class="hover:text-white transition-colors">Sobre Nosotros</a></li>
                    <li><a href="{r}contacto.html" class="hover:text-white transition-colors">Contacto</a></li>
                </ul>
                <ul class="space-y-2 text-sm">
                    <li><a href="{r}privacidad.html" class="hover:text-white transition-colors">Privacidad</a></li>
                    <li><a href="{r}terminos.html" class="hover:text-white transition-colors">Términos</a></li>
                </ul>
            </div>
        </div>
        <div class="pt-8 text-center text-xs text-slate-500">
            <p>&copy; <span id="copyright-year">2026</span> {SITE_NAME} &middot; Todos los derechos reservados</p>
            <p class="mt-3 text-[10px] text-slate-600 max-w-2xl mx-auto">El contenido de este sitio es informativo y educativo. No constituye asesoría financiera, de inversión ni recomendación de compra o venta de ningún instrumento financiero.</p>
        </div>
    </div>
</footer>

<div id="cookie-banner" class="fixed bottom-0 left-0 right-0 z-[100] bg-white border-t border-slate-200 shadow-[0_-4px_20px_rgba(0,0,0,0.1)] p-5 hidden">
    <div class="max-w-4xl mx-auto flex flex-col md:flex-row items-center gap-4">
        <p class="text-sm text-slate-600 flex-1">
            Usamos cookies propias y de terceros (como Google Analytics) para analizar el uso del sitio. Puedes aceptarlas o rechazarlas — las esenciales para que el sitio funcione se mantienen siempre activas.
            <a href="{r}privacidad.html" class="text-emerald-600 hover:underline">Más información</a>
        </p>
        <div class="flex gap-2 flex-shrink-0">
            <button onclick="rejectCookies()" class="px-4 py-2 text-sm font-semibold text-slate-600 border border-slate-300 rounded-lg hover:bg-slate-50 transition-colors">Rechazar</button>
            <button onclick="acceptCookies()" class="px-4 py-2 text-sm font-semibold text-white bg-emerald-600 rounded-lg hover:bg-emerald-700 transition-colors">Aceptar</button>
        </div>
    </div>
</div>
<script src="{r}js/app.js"></script>
<script>
document.addEventListener('DOMContentLoaded', function() {{
    lucide.createIcons();
    document.getElementById("copyright-year").textContent = new Date().getFullYear();
    initCookieBanner();
}});

// --- Consentimiento de cookies ---
function initCookieBanner() {{
    const saved = localStorage.getItem('cookie_consent');
    if (saved === 'accepted') {{
        applyConsent(true);
    }} else if (saved === 'rejected') {{
        applyConsent(false);
    }} else {{
        const banner = document.getElementById('cookie-banner');
        if (banner) banner.classList.remove('hidden');
    }}
}}
function applyConsent(granted) {{
    if (typeof gtag !== 'function') return;
    gtag('consent', 'update', {{
        'ad_storage': granted ? 'granted' : 'denied',
        'analytics_storage': granted ? 'granted' : 'denied',
        'ad_user_data': granted ? 'granted' : 'denied',
        'ad_personalization': granted ? 'granted' : 'denied'
    }});
}}
function acceptCookies() {{
    localStorage.setItem('cookie_consent', 'accepted');
    applyConsent(true);
    document.getElementById('cookie-banner').classList.add('hidden');
}}
function rejectCookies() {{
    localStorage.setItem('cookie_consent', 'rejected');
    applyConsent(false);
    document.getElementById('cookie-banner').classList.add('hidden');
}}
</script>
</body>
</html>
"""


def esc(s):
    return (str(s) or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def article_card(n, cat_url):
    """Tarjeta en formato FILA horizontal (imagen a la izquierda, texto a la
    derecha) — deliberadamente distinta al formato de tarjeta vertical usado
    en otros sitios del mismo grupo, para que la estructura visual no se sienta
    como una plantilla repetida."""
    url = article_url(n)
    return f"""
<article class="flex gap-4 items-start bg-white rounded-xl border border-slate-100 p-3 hover:border-emerald-200 transition-colors">
    <a href="{url}" class="flex-shrink-0">
        <img src="{n['images'][0]}" class="w-28 h-20 md:w-36 md:h-24 object-cover rounded-lg" alt="{esc(n['title'])}" loading="lazy">
    </a>
    <div class="min-w-0">
        <a href="{cat_url}" class="text-emerald-700 font-semibold text-[10px] uppercase tracking-wide">{esc(n['category'])}</a>
        <a href="{url}"><h3 class="font-bold mt-1 mb-1 line-clamp-2 text-slate-800 leading-snug">{esc(n['title'])}</h3></a>
        <p class="text-slate-400 text-[11px]">{fmt_date(n['date'])} &middot; {esc(n['author'])}</p>
    </div>
</article>"""


def fmt_date(iso_date):
    try:
        d = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
                 "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
        return f"{d.day} de {meses[d.month-1]} de {d.year}"
    except Exception:
        return iso_date[:10]


def article_url(n):
    return f"{SITE_URL}/{category_slug(n['category'])}/{slugify(n['title'])}-{n['id']}/"


def article_dir_path(n):
    """Ruta relativa en disco (sin SITE_URL) de la carpeta de un artículo."""
    return f"{category_slug(n['category'])}/{slugify(n['title'])}-{n['id']}/"


def category_url(cat):
    return f"{SITE_URL}/{category_slug(cat)}/"


def author_url(author):
    return f"{SITE_URL}/autor/{slugify(author)}/"


# --- Generadores de páginas ---

def write(path, content):
    full = os.path.join(ROOT, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def quick_summary_bullets(content, max_bullets=3):
    """Extrae 2-3 puntos clave de forma mecánica (primera oración de los
    primeros párrafos), para el cuadro de "Resumen rápido" de cada artículo."""
    paragraphs = [p.strip() for p in content.split("\n") if p.strip()]
    bullets = []
    for p in paragraphs[:max_bullets]:
        sentence = re.split(r"(?<=[.!?])\s+", p)[0].strip()
        if sentence and len(sentence) > 15:
            bullets.append(sentence)
    return bullets[:max_bullets]


def generate_article_page(n, news):
    url = article_url(n)
    cat_url = category_url(n["category"])
    auth_url = author_url(n["author"])
    description = (n["content"][:157] + "...") if len(n["content"]) > 160 else n["content"]
    description = re.sub(r"\s+", " ", description).strip()
    image = n["images"][0] if n.get("images") else ""

    ld_article = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": n["title"],
        "description": description,
        "image": [image] if image else [],
        "datePublished": n["date"],
        "dateModified": n["date"],
        "author": {"@type": "Person", "name": n["author"]},
        "publisher": {
            "@type": "Organization",
            "name": SITE_NAME,
            "logo": {"@type": "ImageObject", "url": f"{SITE_URL}/logo/logo.svg"},
        },
        "mainEntityOfPage": {"@type": "WebPage", "@id": url},
        "articleSection": n["category"],
    }
    crumbs = [("Inicio", f"{SITE_URL}/"), (n["category"], cat_url), (n["title"], None)]
    ld_breadcrumb = breadcrumb_ld(crumbs)
    extra_ld = (
        f'<script type="application/ld+json">{json.dumps(ld_article, ensure_ascii=False)}</script>\n'
        f'    <script type="application/ld+json">{json.dumps(ld_breadcrumb, ensure_ascii=False)}</script>'
    )

    related = [a for a in news if a["category"] == n["category"] and a["id"] != n["id"]][:3]
    related_html = "".join(article_card(a, cat_url) for a in related) or ""

    summary_bullets = quick_summary_bullets(n["content"])
    summary_html = ""
    if summary_bullets:
        items = "".join(f"<li class='flex gap-2'><i data-lucide='check' class='w-4 h-4 text-emerald-600 flex-shrink-0 mt-0.5'></i><span>{esc(b)}</span></li>" for b in summary_bullets)
        summary_html = f"""
        <div class="bg-emerald-50 border border-emerald-200 rounded-xl p-5 my-8">
            <p class="text-emerald-800 font-bold text-xs uppercase tracking-wide mb-3 flex items-center gap-2"><i data-lucide="list-checks" class="w-4 h-4"></i> Resumen rápido</p>
            <ul class="text-sm text-slate-700 space-y-2">{items}</ul>
        </div>"""

    paragraphs = "".join(f"<p class='mb-5 leading-relaxed text-slate-700'>{esc(p)}</p>"
                          for p in n["content"].split("\n") if p.strip())

    title_esc = esc(n["title"])
    hero_image_html = "".join(
        f'<div class="mb-10"><img src="{img}" alt="{title_esc}" class="w-full rounded-2xl shadow-lg" loading="lazy"></div>'
        for img in n.get("images", [])[:1]
    )
    source_html = ""
    if n.get("source_name", "").strip():
        source_html = f'<p class="text-xs text-slate-400 mt-1">Basado en información de <span class="font-medium text-slate-500">{esc(n["source_name"])}</span></p>'

    body = f"""
{nav(url, news)}
{breadcrumbs(crumbs, url)}
<main class="max-w-3xl mx-auto px-4 py-10">
    <article>
        <a href="{cat_url}" class="text-emerald-600 font-bold text-xs uppercase tracking-widest">{esc(n['category'])}</a>
        <h1 class="text-3xl md:text-5xl font-display font-bold mt-4 mb-6 leading-tight">{esc(n['title'])}</h1>
        <div class="flex items-center gap-4 text-slate-500 text-sm border-y border-slate-100 py-4 mb-2">
            <div class="w-10 h-10 bg-slate-200 rounded-full flex items-center justify-center"><i data-lucide="user" class="w-5 h-5"></i></div>
            <div>
                <a href="{auth_url}" class="font-bold text-black hover:underline">{esc(n['author'])}</a>
                <p class="text-xs text-slate-400">Publicado: {fmt_date(n['date'])}</p>
                {source_html}
            </div>
        </div>
        {summary_html}
        {hero_image_html}
        <div class="prose prose-lg max-w-none">
            {paragraphs}
        </div>
    </article>

    {"<h2 class='text-xl font-display font-bold mt-16 mb-6'>Artículos relacionados</h2><div class='space-y-4'>" + related_html + "</div>" if related else ""}
</main>
{footer(url)}
"""
    html = head(f"{n['title']} | {SITE_NAME}", description, url, og_type="article", og_image=image, extra_ld=extra_ld) + body
    rel_path = f"{category_slug(n['category'])}/{slugify(n['title'])}-{n['id']}/index.html"
    write(rel_path, html)
    return url


def generate_category_page(category, news):
    url = category_url(category)
    articles = [a for a in news if a["category"] == category]
    articles.sort(key=lambda a: a["date"], reverse=True)
    description = f"Artículos de {category} en {SITE_NAME}. Análisis y educación financiera con información verificada."
    crumbs = [("Inicio", f"{SITE_URL}/"), (category, None)]
    cards = "".join(article_card(a, url) for a in articles)
    noindex = len(articles) < MIN_ARTICLES_CATEGORY_INDEXABLE
    body = f"""
{nav(url, news)}
{breadcrumbs(crumbs, url)}
<main class="max-w-3xl mx-auto px-4 py-10">
    <h1 class="text-3xl font-display font-bold mb-10">{esc(category)}</h1>
    <div class="space-y-4">
        {cards if articles else '<p class="text-slate-400 py-10 text-center">Todavía no hay artículos en esta sección.</p>'}
    </div>
</main>
{footer(url)}
"""
    html = head(f"{category} | {SITE_NAME}", description, url, noindex=noindex) + body
    write(f"{category_slug(category)}/index.html", html)
    return url, noindex


def generate_author_page(author, news):
    url = author_url(author)
    articles = [a for a in news if a["author"] == author]
    articles.sort(key=lambda a: a["date"], reverse=True)
    bio = AUTHOR_BIOS.get(author, f"Redactor/a de {SITE_NAME}.")
    description = f"Artículos de {author} en {SITE_NAME}. {bio}"
    crumbs = [("Inicio", f"{SITE_URL}/"), ("Autores", None), (author, None)]
    cards = "".join(article_card(a, url) for a in articles)
    noindex = len(articles) < MIN_ARTICLES_AUTHOR_INDEXABLE
    body = f"""
{nav(url, news)}
{breadcrumbs(crumbs, url)}
<main class="max-w-3xl mx-auto px-4 py-10">
    <div class="mb-10">
        <div class="w-16 h-16 bg-slate-200 rounded-full flex items-center justify-center mb-4"><i data-lucide="user" class="w-8 h-8"></i></div>
        <h1 class="text-3xl font-display font-bold mb-2">{esc(author)}</h1>
        <p class="text-slate-500 max-w-2xl">{esc(bio)}</p>
    </div>
    <div class="space-y-4">
        {cards if articles else '<p class="text-slate-400 py-10 text-center">Sin artículos publicados todavía.</p>'}
    </div>
</main>
{footer(url)}
"""
    html = head(f"{author} | {SITE_NAME}", description, url, noindex=noindex) + body
    write(f"autor/{slugify(author)}/index.html", html)
    return url, noindex


GLOSSARY_TERMS = [
    ("Activo", "Cualquier recurso con valor económico que una persona o empresa posee, como efectivo, propiedades o inversiones."),
    ("Liquidez", "Qué tan rápido un activo puede convertirse en efectivo sin perder valor significativo."),
    ("Rendimiento", "La ganancia o pérdida generada por una inversión, expresada como porcentaje sobre el monto invertido."),
    ("Diversificación", "Repartir el dinero entre distintos tipos de inversión para reducir el riesgo general."),
    ("Volatilidad", "Qué tanto y con qué frecuencia cambia el precio de un activo en un periodo de tiempo."),
]


def generate_homepage(news):
    url = f"{SITE_URL}/"
    news_sorted = sorted(news, key=lambda a: a["date"], reverse=True)
    featured = news_sorted[0] if news_sorted else None
    latest = news_sorted[1:11]

    categories = sorted(set(a["category"] for a in news))

    featured_html = ""
    if featured:
        featured_html = f"""
        <a href="{article_url(featured)}" class="block bg-slate-900 rounded-2xl p-8 md:p-10 group">
            <span class="text-emerald-400 font-bold text-xs uppercase tracking-widest">{esc(featured['category'])} &middot; Destacado</span>
            <h2 class="text-2xl md:text-3xl font-display font-bold text-white my-4 group-hover:text-emerald-300 transition-colors">{esc(featured['title'])}</h2>
            <p class="text-slate-300 leading-relaxed max-w-2xl">{esc(featured['content'][:200])}...</p>
            <p class="text-slate-500 text-xs mt-6">{esc(featured['author'])} &middot; {fmt_date(featured['date'])}</p>
        </a>"""

    latest_html = "".join(article_card(a, category_url(a["category"])) for a in latest)
    if not latest_html and not featured:
        latest_html = '<p class="text-slate-400 text-center py-16">Todavía no hay artículos publicados. Vuelve pronto.</p>'

    glossary_html = "".join(
        f"""<div class="pb-4 border-b border-slate-100 last:border-0 last:pb-0">
            <p class="font-bold text-sm text-slate-800">{esc(term)}</p>
            <p class="text-xs text-slate-500 mt-1 leading-relaxed">{esc(definition)}</p>
        </div>""" for term, definition in GLOSSARY_TERMS
    )

    topic_pills = "".join(
        f'<a href="{category_url(c)}" class="px-4 py-2 bg-white border border-slate-200 rounded-full text-xs font-semibold text-slate-600 hover:border-emerald-400 hover:text-emerald-700 transition-colors">{esc(CATEGORY_DISPLAY_NAMES.get(c, c))}</a>'
        for c in categories
    )

    ld_org = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": SITE_NAME,
        "url": url,
        "logo": f"{SITE_URL}/logo/logo.svg",
        "description": SITE_DESCRIPTION,
    }
    extra_ld = f'<script type="application/ld+json">{json.dumps(ld_org, ensure_ascii=False)}</script>'

    body = f"""
{nav(url, news)}
<main class="max-w-6xl mx-auto px-4 py-10">
    <section class="mb-10">{featured_html}</section>

    <section class="mb-12">
        <p class="text-xs font-bold uppercase tracking-widest text-slate-400 mb-3">Explora por tema</p>
        <div class="flex flex-wrap gap-2">{topic_pills}</div>
    </section>

    <div class="grid grid-cols-1 lg:grid-cols-12 gap-10">
        <div class="lg:col-span-8">
            <h2 class="text-2xl font-display font-bold mb-6">Últimos artículos</h2>
            <div class="space-y-4">{latest_html}</div>
        </div>
        <aside class="lg:col-span-4">
            <div class="bg-white border border-slate-200 p-6 rounded-2xl sticky top-24">
                <h3 class="text-sm font-bold mb-5 flex items-center gap-2 uppercase tracking-wide text-slate-700">
                    <i data-lucide="book-open" class="text-emerald-600 w-4 h-4"></i> Glosario rápido
                </h3>
                <div class="space-y-4">{glossary_html}</div>
            </div>
        </aside>
    </div>
</main>
{footer(url)}
"""
    html = head(f"{SITE_NAME} | {SITE_TAGLINE}",
                 SITE_DESCRIPTION,
                 url, extra_ld=extra_ld) + body
    write("index.html", html)


def generate_sitemap(news):
    static_pages = [
        (f"{SITE_URL}/", "daily", "1.0"),
        (f"{SITE_URL}/sobre-nosotros.html", "monthly", "0.8"),
        (f"{SITE_URL}/contacto.html", "monthly", "0.8"),
        (f"{SITE_URL}/privacidad.html", "yearly", "0.5"),
        (f"{SITE_URL}/terminos.html", "yearly", "0.5"),
    ]
    categories = sorted(set(a["category"] for a in news))
    authors = sorted(set(a["author"] for a in news))

    parts = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, freq, pri in static_pages:
        parts.append(f"\n  <url>\n    <loc>{loc}</loc>\n    <changefreq>{freq}</changefreq>\n    <priority>{pri}</priority>\n  </url>")
    for cat in categories:
        count = sum(1 for a in news if a["category"] == cat)
        if count < MIN_ARTICLES_CATEGORY_INDEXABLE:
            continue  # página delgada, marcada noindex — no la metemos en el sitemap
        parts.append(f"\n  <url>\n    <loc>{category_url(cat)}</loc>\n    <changefreq>daily</changefreq>\n    <priority>0.8</priority>\n  </url>")
    for author in authors:
        count = sum(1 for a in news if a["author"] == author)
        if count < MIN_ARTICLES_AUTHOR_INDEXABLE:
            continue
        parts.append(f"\n  <url>\n    <loc>{author_url(author)}</loc>\n    <changefreq>weekly</changefreq>\n    <priority>0.5</priority>\n  </url>")
    for n in news:
        lastmod = n.get("date", "")[:10]
        parts.append(f"\n  <url>\n    <loc>{article_url(n)}</loc>\n    <lastmod>{lastmod}</lastmod>\n    <changefreq>weekly</changefreq>\n    <priority>0.7</priority>\n  </url>")
    parts.append("\n</urlset>\n")
    write("sitemap.xml", "".join(parts))


PROTECTED_TOP_LEVEL = {
    "admin", "css", "js", "images", "logo", "data", ".github", "scripts",
    "buscar", ".git", "build",
}


def clean_generated_dirs():
    """Borra carpetas de categorías/autores generadas en corridas anteriores
    (por ejemplo, si una noticia cambió de título y el slug ya no coincide,
    la carpeta vieja quedaría huérfana con contenido desactualizado)."""
    import shutil
    for entry in os.listdir(ROOT):
        full = os.path.join(ROOT, entry)
        if not os.path.isdir(full) or entry in PROTECTED_TOP_LEVEL or entry.startswith("."):
            continue
        shutil.rmtree(full)


def generate_static_pages():
    """Páginas legales/institucionales — contenido propio de Nueva Finanza,
    reflejando exactamente las tecnologías que este sitio usa."""
    pages = {}

    pages["sobre-nosotros.html"] = ("Sobre Nosotros", "Quiénes somos y qué hace Nueva Finanza.", f"""
        <h1 class="text-3xl font-display font-bold mb-8">Sobre Nueva Finanza</h1>
        <div class="prose prose-lg max-w-none space-y-6 text-slate-700">
            <p>Nueva Finanza es un sitio de contenido educativo sobre economía, mercados, inversión y finanzas personales, escrito en español y pensado para explicar temas financieros de forma clara, sin jerga innecesaria.</p>
            <h2 class="text-xl font-bold mt-8 mb-3">Nuestro enfoque</h2>
            <p>No somos un servicio de asesoría financiera ni de inversión. El contenido que publicamos es informativo y educativo: busca ayudar al lector a entender conceptos financieros —qué es un fondo indexado, cómo funciona la inflación, qué diferencia a una acción de un bono— sin recomendar decisiones específicas de compra, venta o inversión.</p>
            <h2 class="text-xl font-bold mt-8 mb-3">Cómo trabajamos</h2>
            <p>Nuestros artículos se basan en información pública y conceptos ampliamente aceptados dentro de la educación financiera. Evitamos citar cifras o eventos específicos que no podamos verificar, y no atribuimos declaraciones a personas o entidades reales sin una fuente confirmada.</p>
            <h2 class="text-xl font-bold mt-8 mb-3">Contacto editorial</h2>
            <p>Puedes escribirnos a través de nuestra <a href="contacto.html" class="text-emerald-600 hover:underline">página de contacto</a> para sugerencias, correcciones o consultas.</p>
        </div>
    """)

    pages["contacto.html"] = ("Contacto", "Cómo contactar a Nueva Finanza.", """
        <h1 class="text-3xl font-display font-bold mb-8">Contacto</h1>
        <div class="prose prose-lg max-w-none space-y-4 text-slate-700">
            <p>¿Tienes una consulta, sugerencia o encontraste un error en algún artículo? Escríbenos:</p>
            <p><strong>Correo general:</strong> <a href="mailto:contacto@nuevafinanza.com" class="text-emerald-600 hover:underline">contacto@nuevafinanza.com</a></p>
            <p><strong>Correo editorial / correcciones:</strong> <a href="mailto:editorial@nuevafinanza.com" class="text-emerald-600 hover:underline">editorial@nuevafinanza.com</a></p>
            <p class="text-sm text-slate-500 mt-8">Nota: las direcciones de correo deben configurarse para que funcionen de verdad antes de publicar el sitio.</p>
        </div>
    """)

    pages["privacidad.html"] = ("Política de Privacidad", "Política de privacidad de Nueva Finanza.", f"""
        <h1 class="text-3xl font-display font-bold mb-4">Política de Privacidad</h1>
        <p class="text-slate-400 text-sm mb-8">Última actualización: {datetime.now(timezone.utc).strftime('%d de %B de %Y')}</p>
        <div class="prose prose-lg max-w-none space-y-4 text-slate-700">
            <p>En Nueva Finanza respetamos la privacidad de quienes visitan este sitio. Esta política explica qué información recopilamos y cómo la usamos.</p>
            <h2 class="text-xl font-bold mt-8 mb-3">1. Responsable del tratamiento</h2>
            <p>El responsable de este sitio es Nueva Finanza, accesible en nuevafinanza.com. Para consultas sobre privacidad, escribe a <a href="mailto:contacto@nuevafinanza.com" class="text-emerald-600 hover:underline">contacto@nuevafinanza.com</a>.</p>
            <h2 class="text-xl font-bold mt-8 mb-3">2. Información que recopilamos</h2>
            <ul class="list-disc pl-6 space-y-1">
                <li>Datos de uso (páginas visitadas, tiempo de permanencia, dispositivo, navegador) a través de Google Analytics.</li>
                <li>Datos de contacto que envíes voluntariamente a través del correo de contacto.</li>
                <li>Cookies propias y de terceros para analítica y, cuando esté activo, publicidad.</li>
            </ul>
            <h2 class="text-xl font-bold mt-8 mb-3">3. Publicidad</h2>
            <p>Este sitio puede mostrar anuncios a través de Google AdSense una vez sea aprobado. Google puede usar cookies para mostrar anuncios basados en visitas anteriores a este u otros sitios. Puedes gestionar tus preferencias de anuncios en los <a href="https://adssettings.google.com" class="text-emerald-600 hover:underline" target="_blank" rel="noopener">ajustes de anuncios de Google</a>.</p>
            <h2 class="text-xl font-bold mt-8 mb-3">4. Análisis</h2>
            <p>Usamos Google Analytics para entender el tráfico del sitio de forma agregada y anónima. Puedes consultar la <a href="https://policies.google.com/privacy" class="text-emerald-600 hover:underline" target="_blank" rel="noopener">política de privacidad de Google</a> para más información.</p>
            <h2 class="text-xl font-bold mt-8 mb-3">5. Tus derechos</h2>
            <p>Puedes solicitar acceso, corrección o eliminación de cualquier dato personal que nos hayas compartido, escribiendo a nuestro correo de contacto.</p>
        </div>
    """)

    pages["terminos.html"] = ("Términos y Condiciones", "Términos y condiciones de uso de Nueva Finanza.", f"""
        <h1 class="text-3xl font-display font-bold mb-4">Términos y Condiciones</h1>
        <p class="text-slate-400 text-sm mb-8">Última actualización: {datetime.now(timezone.utc).strftime('%d de %B de %Y')}</p>
        <div class="prose prose-lg max-w-none space-y-4 text-slate-700">
            <h2 class="text-xl font-bold mt-8 mb-3">1. Naturaleza del contenido</h2>
            <p>Todo el contenido publicado en Nueva Finanza tiene fines informativos y educativos. <strong>No constituye asesoría financiera, legal, fiscal ni de inversión</strong>, y no debe interpretarse como una recomendación para comprar, vender o mantener ningún instrumento financiero. Antes de tomar decisiones financieras importantes, consulta con un profesional certificado.</p>
            <h2 class="text-xl font-bold mt-8 mb-3">2. Uso del sitio</h2>
            <p>Puedes usar este sitio para fines personales y no comerciales. No está permitido reproducir, distribuir o modificar el contenido sin autorización previa.</p>
            <h2 class="text-xl font-bold mt-8 mb-3">3. Propiedad intelectual</h2>
            <p>Los textos, gráficos y diseño de este sitio son propiedad de Nueva Finanza, salvo el material atribuido a terceros bajo sus propias licencias.</p>
            <h2 class="text-xl font-bold mt-8 mb-3">4. Enlaces externos</h2>
            <p>Este sitio puede contener enlaces a sitios de terceros. No nos hacemos responsables por el contenido o las políticas de privacidad de esos sitios externos.</p>
            <h2 class="text-xl font-bold mt-8 mb-3">5. Limitación de responsabilidad</h2>
            <p>Nos esforzamos por publicar información precisa, pero no garantizamos que el contenido esté siempre libre de errores. El uso de la información publicada es responsabilidad exclusiva del lector.</p>
            <h2 class="text-xl font-bold mt-8 mb-3">6. Contacto</h2>
            <p>Para consultas sobre estos términos, escribe a <a href="mailto:contacto@nuevafinanza.com" class="text-emerald-600 hover:underline">contacto@nuevafinanza.com</a>.</p>
        </div>
    """)

    for filename, (title, description, body_content) in pages.items():
        url = f"{SITE_URL}/{filename}"
        html = head(f"{title} | {SITE_NAME}", description, url) + f"""
{nav(url)}
<main class="max-w-3xl mx-auto px-4 py-14">
    {body_content}
</main>
{footer(url)}
"""
        write(filename, html)

    # 404 personalizada
    url = f"{SITE_URL}/404.html"
    html = head(f"Página no encontrada | {SITE_NAME}", "La página que buscas no existe.", url, noindex=True) + f"""
{nav(url)}
<main class="min-h-[60vh] flex items-center justify-center px-4">
    <div class="text-center max-w-md">
        <p class="text-emerald-600 font-bold text-xs uppercase tracking-widest mb-4">Error 404</p>
        <h1 class="font-display text-4xl font-bold mb-6">Página no encontrada</h1>
        <p class="text-slate-500 mb-8 leading-relaxed">La página que buscas no existe, fue movida o el enlace está roto.</p>
        <a href="/" class="inline-block bg-emerald-600 text-white px-6 py-3 rounded-xl font-bold text-sm hover:bg-emerald-700 transition-colors">Volver al inicio</a>
    </div>
</main>
{footer(url)}
"""
    write("404.html", html)


def build_all(news=None):
    clean_generated_dirs()
    news = news or load_news()
    valid_news = []
    for n in news:
        try:
            validate_article(n)
            valid_news.append(n)
        except ArticleValidationError as e:
            print(f"⚠️  Saltando artículo inválido: {e}")
    for n in valid_news:
        generate_article_page(n, valid_news)
    for cat in sorted(set(a["category"] for a in valid_news)):
        generate_category_page(cat, valid_news)
    for author in sorted(set(a["author"] for a in valid_news)):
        generate_author_page(author, valid_news)
    generate_homepage(valid_news)
    generate_redirects(valid_news)
    generate_sitemap(valid_news)
    generate_static_pages()
    return valid_news


def build_incremental(new_article, news):
    """Regenera solo lo afectado por una noticia nueva (usado por auto_publish.py
    y por publish_new). Lanza ArticleValidationError si la noticia no cumple el
    mínimo — el llamador debe abortar la publicación en ese caso."""
    validate_article(new_article)
    generate_article_page(new_article, news)
    generate_category_page(new_article["category"], news)
    generate_author_page(new_article["author"], news)
    generate_homepage(news)
    generate_sitemap(news)


# ============================================================
# Redirecciones (para cuando cambia el slug de un artículo editado)
# ============================================================

REDIRECTS_PATH = os.path.join(ROOT, "data", "redirects.json")


def load_redirects():
    if not os.path.exists(REDIRECTS_PATH):
        return []
    with open(REDIRECTS_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_redirects(redirects):
    with open(REDIRECTS_PATH, "w", encoding="utf-8") as f:
        json.dump(redirects, f, ensure_ascii=False, indent=2)


def add_redirect(old_path, new_url):
    """Registra old_path -> new_url. Si ya existía alguna redirección que
    apuntaba hacia old_path, la reescribe para que apunte directo a new_url
    — así nunca se encadenan dos saltos, siempre queda uno solo."""
    redirects = load_redirects()
    old_path_url = f"{SITE_URL}/{old_path}"
    for r in redirects:
        if r["to"] == old_path_url:
            r["to"] = new_url
    redirects = [r for r in redirects if r["from"] != old_path]
    redirects.append({"from": old_path, "to": new_url})
    save_redirects(redirects)


def generate_redirects(news):
    """Genera una página de redirección (meta-refresh + canonical + JS) en cada
    ruta vieja registrada en data/redirects.json. Un solo salto: si la URL
    nueva también cambió después, se actualiza el registro, no se encadenan.
    Se salta cualquier ruta que hoy coincida con un artículo real (evita
    pisar contenido válido por error)."""
    redirects = load_redirects()
    live_paths = {article_dir_path(n) for n in news}
    for r in redirects:
        if r["from"] in live_paths:
            continue  # esa ruta ya la ocupa un artículo real, no se toca
        html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="0; url={r['to']}">
<link rel="canonical" href="{r['to']}">
<meta name="robots" content="noindex, follow">
<title>Redirigiendo... | {SITE_NAME}</title>
<script>window.location.replace("{r['to']}");</script>
</head>
<body>
<p>Esta noticia se movió. <a href="{r['to']}">Haz clic aquí si no eres redirigido automáticamente</a>.</p>
</body>
</html>
"""
        write(r["from"] + "index.html" if not r["from"].endswith("index.html") else r["from"], html)


# ============================================================
# Git compartido (usado por auto_publish.py y manual_publish.py)
# ============================================================

def git(*args, gh_token, owner, repo):
    remote_url = f"https://x-access-token:{gh_token}@github.com/{owner}/{repo}.git"
    if args and args[0] == "push":
        subprocess.run(["git", "push", remote_url, "HEAD:main"], cwd=ROOT, check=True)
    else:
        subprocess.run(["git", *args], cwd=ROOT, check=True)


def commit_and_push(message, gh_token, owner=GITHUB_OWNER, repo=GITHUB_REPO):
    subprocess.run(["git", "config", "user.name", f"{SITE_NAME} Bot"], cwd=ROOT, check=True)
    subprocess.run(["git", "config", "user.email", "actions@users.noreply.github.com"], cwd=ROOT, check=True)
    subprocess.run(["git", "add", "-A"], cwd=ROOT, check=True)
    result = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
    if result.returncode == 0:
        print("Sin cambios que publicar.")
        return False
    subprocess.run(["git", "commit", "-m", message], cwd=ROOT, check=True)
    git("push", gh_token=gh_token, owner=owner, repo=repo)
    return True


# ============================================================
# API de alto nivel: ÚNICA lógica de publicar/editar/borrar.
# La usan por igual auto_publish.py (automático) y manual_publish.py (panel).
# ============================================================

def publish_new(entry, news):
    """Valida y agrega un artículo nuevo. Lanza ArticleValidationError si no
    cumple el mínimo — en ese caso NO se debe escribir nada a disco."""
    validate_article(entry)
    updated_news = [entry] + news
    with open(NEWS_PATH, "w", encoding="utf-8") as f:
        json.dump(updated_news, f, ensure_ascii=False, indent=2)
    build_incremental(entry, updated_news)
    return updated_news


def apply_edit(article_id, changes, news):
    """Edita un artículo existente. `changes` es un dict con los campos a
    actualizar (title/content/category/author/images). La fecha original NUNCA
    se toca automáticamente (no se falsean fechas de publicación)."""
    old_entry = next((n for n in news if n["id"] == article_id), None)
    if old_entry is None:
        raise ArticleValidationError(f"No existe ninguna noticia con id={article_id}")

    old_path = article_dir_path(old_entry)
    old_category = old_entry["category"]
    old_author = old_entry["author"]

    updated_entry = dict(old_entry)
    for key in ("title", "content", "category", "author", "images"):
        if key in changes and changes[key] not in (None, ""):
            updated_entry[key] = changes[key]

    validate_article(updated_entry)  # si falla, no se escribe nada

    updated_news = [updated_entry if n["id"] == article_id else n for n in news]
    with open(NEWS_PATH, "w", encoding="utf-8") as f:
        json.dump(updated_news, f, ensure_ascii=False, indent=2)

    new_path = article_dir_path(updated_entry)
    if new_path != old_path:
        # El slug cambió: borrar la carpeta vieja y dejar una redirección
        # de un solo salto hacia la URL nueva.
        old_full = os.path.join(ROOT, old_path)
        if os.path.isdir(old_full):
            import shutil
            shutil.rmtree(old_full)
        add_redirect(old_path, article_url(updated_entry))

    affected_categories = {old_category, updated_entry["category"]}
    affected_authors = {old_author, updated_entry["author"]}
    for cat in affected_categories:
        generate_category_page(cat, updated_news)
    for author in affected_authors:
        generate_author_page(author, updated_news)
    generate_article_page(updated_entry, updated_news)
    generate_homepage(updated_news)
    generate_redirects(updated_news)
    generate_sitemap(updated_news)
    return updated_news


def apply_delete(article_id, news):
    """Elimina un artículo por completo: de news.json, su carpeta HTML, de
    todas las páginas que lo listaban, y de cualquier redirección que
    apuntara hacia él (para no dejar redirecciones huérfanas apuntando a
    una página que ya no existe)."""
    entry = next((n for n in news if n["id"] == article_id), None)
    if entry is None:
        raise ArticleValidationError(f"No existe ninguna noticia con id={article_id}")

    path = article_dir_path(entry)
    updated_news = [n for n in news if n["id"] != article_id]
    with open(NEWS_PATH, "w", encoding="utf-8") as f:
        json.dump(updated_news, f, ensure_ascii=False, indent=2)

    full_path = os.path.join(ROOT, path)
    if os.path.isdir(full_path):
        import shutil
        shutil.rmtree(full_path)

    article_url_str = article_url(entry)
    redirects = load_redirects()
    orphaned = [r for r in redirects if r["to"] == article_url_str]
    remaining = [r for r in redirects if r["to"] != article_url_str]
    save_redirects(remaining)
    for r in orphaned:
        stub_path = os.path.join(ROOT, r["from"])
        if os.path.isdir(stub_path):
            import shutil
            shutil.rmtree(stub_path)

    generate_category_page(entry["category"], updated_news)
    generate_author_page(entry["author"], updated_news)
    generate_homepage(updated_news)
    generate_sitemap(updated_news)
    return updated_news


if __name__ == "__main__":
    build_all()
    print("Sitio estático generado correctamente.")

