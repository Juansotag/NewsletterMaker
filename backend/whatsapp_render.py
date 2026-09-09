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
    Convierte el dict del newsletter en un texto formateado para WhatsApp.

    Args:
        newsletter: el dict devuelto por Claude (titulo, fecha, contexto, cifras, items, oportunidades).

    Returns:
        String con formato de WhatsApp listo para enviar por Open-Wa.
    """
    d = newsletter

    titulo   = clean_text(d.get("titulo", "Newsletter Ejecutivo"))
    fecha    = clean_text(d.get("fecha", ""))
    contexto = clean_text(d.get("contexto", ""))

    lines: list[str] = []

    # ── Cabecera ─────────────────────────────────────────────────────────────
    lines.append("🏛 *UNIVERSIDAD DE LA SABANA · GOVLAB*")
    lines.append("────────────────────────")
    lines.append(f"📰 *{titulo.upper()}*")
    
    meta_parts = []
    if fecha:
        meta_parts.append(f"📅 {fecha}")
    if contexto:
        meta_parts.append(f"🎯 {contexto}")
    if meta_parts:
        lines.append(" • ".join(meta_parts))
    lines.append("────────────────────────")
    lines.append("")

    # ── Cifras Clave ─────────────────────────────────────────────────────────
    cifras = d.get("cifras", [])
    if cifras:
        lines.append("📊 *CIFRAS DESTACADAS DEL PERÍODO*")
        for c in cifras:
            dato   = clean_text(c.get("dato", ""))
            ctx_c  = clean_text(c.get("contexto", ""))
            fuente = clean_text(c.get("fuente", ""))
            url_c  = clean_text(c.get("url", ""))

            cifra_line = f"• *{dato}*"
            if ctx_c:
                cifra_line += f" — {ctx_c}"
            if fuente and url_c:
                cifra_line += f"\n   _Fuente: {fuente}_ ({url_c})"
            elif fuente:
                cifra_line += f"\n   _Fuente: {fuente}_"
            elif url_c:
                cifra_line += f"\n   _Enlace:_ {url_c}"

            lines.append(cifra_line)
        lines.append("")

    # ── Ítems Principales ────────────────────────────────────────────────────
    items = d.get("items", [])
    if items:
        lines.append("📌 *RADAR ESTRATÉGICO*")
        lines.append("")

        for i, it in enumerate(items, 1):
            eje       = clean_text(it.get("eje", ""))
            titular   = clean_text(it.get("titular", ""))
            resumen   = clean_text(it.get("resumen", ""))
            pqi       = clean_text(it.get("por_que_importa", ""))
            fuente_i  = clean_text(it.get("fuente", ""))
            fecha_pub = clean_text(it.get("fecha_publicacion", ""))
            url_i     = clean_text(it.get("url", ""))

            eje_header = f"[{eje.upper()}] " if eje else ""
            lines.append(f"*{i}. {eje_header}{titular}*")

            if resumen:
                lines.append(resumen)

            if pqi:
                lines.append(f"💡 *Por qué importa:* {pqi}")

            # Fuente y enlace
            meta_src = []
            if fuente_i:
                meta_src.append(f"Fuente: {fuente_i}")
            if fecha_pub:
                meta_src.append(fecha_pub)
            
            src_str = " · ".join(meta_src)
            if src_str and url_i:
                lines.append(f"🔍 _{src_str}_: {url_i}")
            elif src_str:
                lines.append(f"🔍 _{src_str}_")
            elif url_i:
                lines.append(f"🔗 {url_i}")

            lines.append("")  # Separador entre ítems

    # ── Oportunidades Accionables ────────────────────────────────────────────
    opps = d.get("oportunidades", [])
    if opps:
        lines.append("🎯 *OPORTUNIDADES ACCIONABLES*")
        for o in opps:
            if isinstance(o, str):
                lines.append(f"• {clean_text(o)}")
            else:
                texto    = clean_text(o.get("texto") or o.get("text", ""))
                fuente_o = clean_text(o.get("fuente", ""))
                url_o    = clean_text(o.get("url", ""))

                opp_line = f"• {texto}"
                if fuente_o and url_o:
                    opp_line += f" — _{fuente_o}_ ({url_o})"
                elif fuente_o:
                    opp_line += f" — _{fuente_o}_"
                elif url_o:
                    opp_line += f" ({url_o})"
                lines.append(opp_line)
        lines.append("")

    # ── Pie Institucional ────────────────────────────────────────────────────
    lines.append("────────────────────────")
    lines.append("🏛 _Laboratorio de Gobierno · Universidad de La Sabana_")
    lines.append("_Generado automáticamente por el Sistema de Newsletter Ejecutivo_")

    return "\n".join(lines).strip()
