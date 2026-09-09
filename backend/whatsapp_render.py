"""
backend/whatsapp_render.py
Renderiza el JSON del newsletter como texto enriquecido con el formato nativo de WhatsApp.
Usa sintaxis estándar de WhatsApp: *negrita*, _cursiva_, ~tachado~, `código`.
"""
from __future__ import annotations
import re


def clean_text(s: object) -> str:
    if s is None:
        return ""
    txt = str(s).strip()
    txt = re.sub(r'\n{3,}', '\n\n', txt)
    return txt


def clean_url(url: object) -> str:
    """Limpia la URL eliminando comillas, paréntesis u otros signos de puntuación residuales."""
    if not url:
        return ""
    u = str(url).strip()
    u = re.sub(r'^[<\(\[\"\'\s]+', '', u)
    u = re.sub(r'[>\)\]\"\'\s\.,;]+$', '', u)
    if not u.startswith("http://") and not u.startswith("https://"):
        if u.startswith("www."):
            u = "https://" + u
        elif "." in u and not u.startswith("@"):
            u = "https://" + u
    return u


def render_whatsapp_text(newsletter: dict) -> str:
    """
    Convierte el dict del newsletter en un texto formateado para WhatsApp.
    Usa negrita nativa (*texto*) y URLs limpias sin corchetes ni paréntesis,
    garantizando que WhatsApp las reconozca como enlaces interactivos y no generen 404.
    """
    d = newsletter if isinstance(newsletter, dict) else {}

    titulo   = clean_text(d.get("titulo") or d.get("title") or "Newsletter Ejecutivo: Avances y Oportunidades Clave en Educación e Innovación")
    fecha    = clean_text(d.get("fecha") or d.get("date") or "")
    contexto = clean_text(d.get("contexto") or d.get("descripcion") or "")

    lines: list[str] = []

    # ── Cabecera ─────────────────────────────────────────────────────────────
    lines.append("*Universidad de La Sabana*")
    lines.append(f"*{titulo}*")
    
    if fecha and contexto:
        lines.append(f"{fecha} - {contexto}")
    elif fecha:
        lines.append(fecha)
    elif contexto:
        lines.append(contexto)
    lines.append("")

    # ── Cifras importantes del sector ─────────────────────────────────────────
    cifras = d.get("cifras") or d.get("estadisticas") or []
    if cifras:
        lines.append("*Cifras importantes del sector*")
        lines.append("")
        for c in cifras:
            if isinstance(c, str):
                lines.append(f"*{clean_text(c)}*")
                lines.append("")
                continue
            dato   = clean_text(c.get("dato") or c.get("cifra") or "")
            ctx_c  = clean_text(c.get("contexto") or c.get("descripcion") or "")
            fuente = clean_text(c.get("fuente") or c.get("medio") or "")
            url_c  = clean_url(c.get("url") or c.get("link") or "")

            fecha_pub = clean_text(c.get("fecha_publicacion") or "")
            fuente_label = f"{fuente} · 📅 {fecha_pub}" if (fuente and fecha_pub) else (fuente or fecha_pub)

            if dato:
                lines.append(f"*{dato}*")
            if ctx_c:
                lines.append(ctx_c)
            if fuente_label and url_c:
                lines.append(f"🔗 Fuente ({fuente_label}): {url_c}")
            elif url_c:
                lines.append(f"🔗 Enlace{f' (📅 {fecha_pub})' if fecha_pub else ''}: {url_c}")
            elif fuente_label:
                lines.append(f"Fuente: _{fuente_label}_")
            lines.append("")

    # ── Ítems Principales por Eje ────────────────────────────────────────────
    items = d.get("items") or d.get("noticias") or d.get("articulos") or []
    if items:
        for it in items:
            if not isinstance(it, dict):
                continue
            eje       = clean_text(it.get("eje") or it.get("categoria") or "")
            titular   = clean_text(it.get("titular") or it.get("titulo") or "")
            resumen   = clean_text(it.get("resumen") or it.get("contenido") or "")
            pqi       = clean_text(it.get("por_que_importa") or it.get("importancia") or "")
            fuente_i  = clean_text(it.get("fuente") or "")
            fecha_pub = clean_text(it.get("fecha_publicacion") or "")
            url_i     = clean_url(it.get("url") or it.get("link") or "")
            fuente_label = f"{fuente_i} · 📅 {fecha_pub}" if (fuente_i and fecha_pub) else (fuente_i or fecha_pub)

            if eje:
                lines.append(f"*{eje}*")
            if titular:
                lines.append(f"*{titular}*")
            if resumen:
                lines.append(resumen)
            if pqi:
                lines.append(f"*Por qué importa:* {pqi}")
            if fuente_label and url_i:
                lines.append(f"🔗 Fuente ({fuente_label}): {url_i}")
            elif url_i:
                lines.append(f"🔗 Enlace{f' (📅 {fecha_pub})' if fecha_pub else ''}: {url_i}")
            elif fuente_label:
                lines.append(f"Fuente: _{fuente_label}_")

            lines.append("")  # Separador entre ítems

    # ── Oportunidades Accionables ────────────────────────────────────────────
    opps = d.get("oportunidades") or d.get("convocatorias") or []
    if opps:
        lines.append("*Oportunidades accionables*")
        lines.append("")
        for o in opps:
            if isinstance(o, str):
                lines.append(f"• {clean_text(o)}")
            elif isinstance(o, dict):
                texto    = clean_text(o.get("texto") or o.get("text") or o.get("descripcion") or "")
                fuente_o = clean_text(o.get("fuente") or "")
                url_o    = clean_url(o.get("url") or o.get("link") or "")

                link_part = ""
                if fuente_o and url_o:
                    link_part = f" — 🔗 {fuente_o}: {url_o}"
                elif url_o:
                    link_part = f" — 🔗 {url_o}"
                elif fuente_o:
                    link_part = f" — _{fuente_o}_"

                if texto:
                    lines.append(f"{texto}{link_part}")
                elif link_part:
                    lines.append(link_part.lstrip(" — "))
        lines.append("")

    return "\n".join(lines).strip()
