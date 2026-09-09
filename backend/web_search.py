"""
backend/web_search.py
Módulo de búsqueda web en tiempo real para alimentar a los modelos de OpenAI (GPT-4o).
Permite buscar noticias e información actualizada con enlaces y fechas reales.
"""
from __future__ import annotations
import json
import httpx
from typing import Optional


def perform_web_search(query: str, max_results: int = 5) -> list[dict]:
    """
    Ejecuta una búsqueda web en tiempo real para una consulta dada.
    Retorna una lista de dicts con: title, href, body.
    """
    clean_q = query.strip()
    if not clean_q:
        return []

    # Intento 1: ddgs (DuckDuckGo Search moderno)
    try:
        from ddgs import DDGS
        results = list(DDGS().text(clean_q, max_results=max_results))
        if results:
            formatted = []
            for r in results:
                formatted.append({
                    "title": r.get("title", ""),
                    "url": r.get("href") or r.get("url") or r.get("link", ""),
                    "snippet": r.get("body") or r.get("snippet", ""),
                })
            return formatted
    except Exception as e:
        print(f"[web_search] Error con ddgs: {e}")

    # Intento 2: Fallback ligero DuckDuckGo Instant Answer / HTML
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        with httpx.Client(timeout=8.0, verify=False, headers=headers) as client:
            resp = client.get(
                "https://api.duckduckgo.com/",
                params={"q": clean_q, "format": "json", "no_redirect": "1", "no_html": "1"}
            )
            if resp.status_code == 200:
                data = resp.json()
                topics = data.get("RelatedTopics", [])
                fallback_results = []
                for t in topics[:max_results]:
                    if isinstance(t, dict) and "Text" in t:
                        fallback_results.append({
                            "title": t.get("Text", "")[:60],
                            "url": t.get("FirstURL", ""),
                            "snippet": t.get("Text", ""),
                        })
                if fallback_results:
                    return fallback_results
    except Exception as e:
        print(f"[web_search] Error en fallback: {e}")

    return []


def format_search_results_for_llm(results: list[dict]) -> str:
    """Convierte los resultados de búsqueda en un texto estructurado para el prompt de GPT-4o."""
    if not results:
        return "No se encontraron resultados web relevantes para esta consulta."

    parts = []
    for i, r in enumerate(results, 1):
        title = r.get("title", "Sin título")
        url = r.get("url", "")
        snippet = r.get("snippet", "")
        parts.append(f"[{i}] {title}\nURL: {url}\nResumen: {snippet}")

    return "\n\n".join(parts)
