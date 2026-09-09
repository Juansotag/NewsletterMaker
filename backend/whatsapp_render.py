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
    # Eliminar saltos de línea excesivos dentro de un mismo párrafo
    txt = re.sub(r'\n{3,}', '\n\n', txt)
    return txt


def render_whatsapp_text(newsletter: dict) -> str:
    """
    Convierte el dict del newsletter en un texto formateado para WhatsApp,
    coincidiendo exactamente con el formato ejecutivo de referencia.
    """
    d = newsletter if isinstance(newsletter, dict) else {}

    titulo   = clean_text(d.get("titulo") or d.get("title") or "Newsletter Ejecutivo: Avances y Oportunidades Clave en Educación e Innovación")
    fecha    = clean_text(d.get("fecha") or d.get("date") or "")
    contexto = clean_text(d.get("contexto") or d.get("descripcion") or "")

    lines: list[str] = []

    # ── Cabecera ─────────────────────────────────────────────────────────────
    lines.append("*Universidad de La Sabana*")
    lines.append(f"*{titulo}*")
    
    meta_parts = []
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
            url_c  = clean_text(c.get("url") or c.get("link") or "")

            if dato:
                lines.append(f"*{dato}*")
            if ctx_c:
                lines.append(ctx_c)
            if fuente and url_c:
                lines.append(f"[{fuente} ↗]({url_c})")
            elif url_c:
                lines.append(f"[{url_c} ↗]({url_c})")
            elif fuente:
                lines.append(f"_{fuente}_")
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
            url_i     = clean_text(it.get("url") or it.get("link") or "")

            if eje:
                lines.append(f"*{eje}*")
            if titular and url_i:
                lines.append(f"[{titular}]({url_i})")
            elif titular:
                lines.append(f"*{titular}*")

            if resumen:
                lines.append(resumen)

            if pqi:
                lines.append(f"*Por qué importa:* {pqi}")

            if fuente_i and url_i:
                lines.append(f"Fuente: [{fuente_i} ↗]({url_i})")
            elif fuente_i:
                lines.append(f"Fuente: _{fuente_i}_")
            elif url_i:
                lines.append(f"Enlace: {url_i}")

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
                url_o    = clean_text(o.get("url") or o.get("link") or "")

                if fuente_o and url_o:
                    lines.append(f"{texto} — [{fuente_o} ↗]({url_o})")
                elif url_o:
                    lines.append(f"{texto} — [{url_o} ↗]({url_o})")
                elif fuente_o:
                    lines.append(f"{texto} — _{fuente_o}_")
                elif texto:
                    lines.append(f"{texto}")
        lines.append("")

    return "\n".join(lines).strip()
