#!/usr/bin/env python3
"""
Auto-publicación de artículos para Nueva Finanza.

Flujo:
 1. Trae noticias REALES y recientes de la categoría "business" desde GNews API.
 2. Le pide a Claude que redacte un artículo EDUCATIVO/explicativo original en
    español, basado en esos hechos reales como contexto, con reglas estrictas
    contra inventar datos y contra dar consejos de inversión específicos.
 3. Busca una foto libre de derechos relacionada (Unsplash).
 4. Actualiza data/news.json y genera las páginas HTML reales con generate_site.py.
 5. Hace commit y push directo con git.

Se ejecuta automáticamente por GitHub Actions, o a mano con:
  python3 scripts/auto_publish.py
"""

import os
import sys
import json
import random
import time
from datetime import datetime, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generate_site  # noqa: E402

ROOT = generate_site.ROOT
NEWS_PATH = generate_site.NEWS_PATH
SITE_URL = generate_site.SITE_URL

CATEGORIES = ["Mercados", "Criptomonedas", "Economía", "Finanzas Personales", "Empresas", "Inversión"]
AUTHORS = ["Redacción Nueva Finanza", "Carla Espinal", "Manuel Objío"]

GH_TOKEN = os.environ["GH_TOKEN"].strip()
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"].strip()
GNEWS_API_KEY = os.environ["GNEWS_API_KEY"].strip()
UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "").strip()


# --- Fuente de noticias reales de negocios/economía ---
def fetch_real_news():
    """Combina dos fuentes para tener un fondo más amplio de dónde elegir:
    1) La categoría "business" de GNews (noticias de negocios ya clasificadas).
    2) Una búsqueda directa por palabras clave de finanzas, que cubre términos
       que a veces no caen dentro de la categoría "business" pero sí son
       relevantes (criptomonedas, finanzas personales, mercados, etc.).
    Esto reduce el riesgo de quedarse sin material válido en días donde la
    categoría de negocios en español viene floja."""
    MIN_SOURCE_CHARS = 300
    articles = []
    seen_urls = set()

    sources = [
        ("https://gnews.io/api/v4/top-headlines", {"lang": "es", "category": "business", "max": 10}),
        ("https://gnews.io/api/v4/search", {"lang": "es", "q": "economía OR finanzas OR mercados OR inversión OR criptomonedas", "max": 10}),
    ]

    for url, extra_params in sources:
        params = {**extra_params, "token": GNEWS_API_KEY}
        try:
            r = requests.get(url, params=params, timeout=20)
            r.raise_for_status()
            for a in r.json().get("articles", []):
                link = a.get("url", "")
                if link and link in seen_urls:
                    continue
                if link:
                    seen_urls.add(link)
                articles.append(a)
        except Exception as e:
            print(f"Aviso: falló una de las fuentes de noticias ({url}): {e}")

    return [
        a for a in articles
        if a.get("title") and a.get("description")
        and len(a.get("description", "") + a.get("content", "")) >= MIN_SOURCE_CHARS
    ]


# --- Generación con IA: contenido EDUCATIVO, no "noticia de último momento" ---
def generate_article(source):
    categories_list = ", ".join(CATEGORIES)
    prompt = f"""Eres redactor de "Nueva Finanza", un sitio de educación financiera en español (no un medio de noticias). Te doy información real y reciente sobre economía/negocios; tu trabajo es escribir un artículo EDUCATIVO Y EXPLICATIVO original de 400 a 600 palabras, que use esta noticia como punto de partida para explicar un concepto financiero relacionado al lector — no para simplemente reportar el evento como una noticia de último momento.

Información real de base: {source.get('title')}
Resumen/contenido: {source.get('description', '')} {source.get('content', '')}
Fuente: {source.get('source', {}).get('name', 'medio internacional')}

REGLAS ESTRICTAS (no negociables):
- No inventes datos, cifras, fechas ni hechos que no estén en la información de arriba.
- No inventes citas textuales atribuidas a personas reales. Si mencionas declaraciones, parafrasea de forma general.
- NUNCA des una recomendación específica de comprar, vender, o mantener ningún instrumento financiero. NUNCA des un precio objetivo, una predicción numérica de rendimiento futuro, ni sugieras que algo es "una buena inversión ahora".
- El artículo debe tener un enfoque EDUCATIVO: usa el evento real como gancho o ejemplo, pero el cuerpo debe explicar el concepto financiero de fondo (qué es, cómo funciona, por qué importa) de forma que sea útil incluso para alguien sin conocimientos previos.
- Si la información es insuficiente para 400 palabras factuales, escribe un artículo más corto — nunca rellenes con invenciones.
- Tono claro, didáctico y neutral, en español de Latinoamérica. Evita sonar a titular de noticia de última hora.
- No copies frases textuales del resumen original; redacta todo con tus propias palabras.
- NUNCA incluyas encabezados de plantilla como "Título:", "Categoría:", "Desarrollo de la noticia:" dentro del campo content — solo el texto del artículo en sí, listo para publicar tal cual.

Además:
- Elige la sección que MEJOR describe el tema, solo entre estas opciones: {categories_list}
- Genera una frase corta EN INGLÉS (2-4 palabras) que describa la escena general del tema, para buscar una foto de stock genérica y segura relacionada — NO uses nombres propios ni marcas específicas. Ejemplos válidos: "stock market finance", "business office meeting", "cryptocurrency digital coins", "personal budget planning".

Devuelve SOLO un objeto JSON válido, sin texto adicional, sin markdown, con este formato exacto:
{{"title": "un titular propio, educativo, no sensacionalista", "content": "el cuerpo completo del artículo", "category": "una de las secciones de la lista", "image_query": "frase corta en inglés para buscar la foto"}}
"""
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-5",
            "max_tokens": 1500,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    text = "".join(b["text"] for b in data["content"] if b.get("type") == "text").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


# --- Imagen libre de derechos relacionada al tema ---
def fetch_image(query):
    if not UNSPLASH_ACCESS_KEY:
        return None
    try:
        r = requests.get(
            "https://api.unsplash.com/search/photos",
            params={"query": query, "per_page": 1, "orientation": "landscape"},
            headers={"Authorization": f"Client-ID {UNSPLASH_ACCESS_KEY}"},
            timeout=20,
        )
        r.raise_for_status()
        results = r.json().get("results", [])
        if results:
            return results[0]["urls"]["regular"]
    except Exception as e:
        print(f"Aviso: no se pudo obtener imagen de Unsplash ({e})")
    return None


def main():
    print("Buscando noticias reales de economía/negocios...")
    real_articles = fetch_real_news()
    if not real_articles:
        print("No se encontraron noticias reales en esta corrida. Abortando sin publicar.")
        sys.exit(0)

    source = random.choice(real_articles)
    print(f"Base real elegida: {source['title']}")

    print("Redactando artículo educativo con IA...")
    generated = generate_article(source)

    category = generated.get("category", "").strip()
    if category not in CATEGORIES:
        print(f"Aviso: categoría '{category}' no reconocida, usando 'Economía' por defecto.")
        category = "Economía"

    print("Buscando imagen libre de derechos...")
    image_query = generated.get("image_query", "").strip() or category
    image_url = fetch_image(image_query) or "https://images.unsplash.com/photo-1495020689067-958852a7765e?w=1200"

    with open(NEWS_PATH, encoding="utf-8") as f:
        news = json.load(f)

    new_entry = {
        "id": int(time.time() * 1000),
        "title": generated["title"],
        "content": generated["content"],
        "category": category,
        "author": random.choice(AUTHORS),
        "date": datetime.now(timezone.utc).isoformat(),
        "images": [image_url],
        "views": 0,
        "source_name": source.get("source", {}).get("name", "").strip(),
    }

    print("Validando y generando páginas HTML reales...")
    try:
        generate_site.publish_new(new_entry, news)
    except generate_site.ArticleValidationError as e:
        print(f"❌ El artículo generado no pasó la validación mínima: {e}")
        print("No se publica nada en esta corrida.")
        sys.exit(1)

    print("Publicando en GitHub...")
    generate_site.commit_and_push(f"Auto-publish: {new_entry['title'][:70]}", gh_token=GH_TOKEN)

    url = generate_site.article_url(new_entry)
    print(f"✅ Publicado: {url}")


if __name__ == "__main__":
    main()
