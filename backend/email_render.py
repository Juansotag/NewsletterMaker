"""
backend/email_render.py
Renderiza el JSON del newsletter como HTML de email (CSS inline, columna única, 600 px).
Compatible con Gmail, Outlook y Apple Mail.
"""
from __future__ import annotations
import html as _html

def esc(s: object) -> str:
    return _html.escape(str(s) if s is not None else "")


def render_email_html(newsletter: dict, *, subject: str = "") -> str:
    """
    Convierte el dict del newsletter en un HTML de email completo.

    Args:
        newsletter: el dict tal como lo devuelve Claude (titulo, fecha, items, cifras, oportunidades).
        subject:    asunto del correo (se usa solo como fallback para el preheader).

    Returns:
        String HTML con CSS completamente inline, listo para enviar por Resend.
    """
    d = newsletter

    titulo   = esc(d.get("titulo", "Newsletter Ejecutivo GovLab"))
    fecha    = esc(d.get("fecha", ""))
    contexto = esc(d.get("contexto", ""))

    # ── Cifras ────────────────────────────────────────────────────────────────
    cifras_html = ""
    for c in d.get("cifras", []):
        dato    = esc(c.get("dato", ""))
        ctx_c   = esc(c.get("contexto", ""))
        fuente  = esc(c.get("fuente", ""))
        url_c   = esc(c.get("url", ""))
        src_tag = (
            f'<a href="{url_c}" style="color:#1a3a6b;font-size:11px;">{fuente or url_c}</a>'
            if url_c else
            (f'<span style="font-size:11px;color:#666;">{fuente}</span>' if fuente else "")
        )
        cifras_html += f"""
        <td style="width:30%;padding:10px;vertical-align:top;">
          <div style="background:#f0f4fb;border-radius:8px;padding:14px;text-align:center;">
            <div style="font-size:22px;font-weight:800;color:#1a3a6b;">{dato}</div>
            <div style="font-size:12px;color:#444;margin-top:4px;">{ctx_c}</div>
            {f'<div style="margin-top:6px;">{src_tag}</div>' if src_tag else ''}
          </div>
        </td>"""

    cifras_section = ""
    if cifras_html:
        cifras_section = f"""
      <tr>
        <td style="padding:0 0 24px;">
          <p style="margin:0 0 12px;font-size:13px;font-weight:700;color:#1a3a6b;
                    text-transform:uppercase;letter-spacing:.05em;">
            Cifras del período
          </p>
          <table width="100%" cellpadding="0" cellspacing="0" border="0">
            <tr>{cifras_html}</tr>
          </table>
        </td>
      </tr>"""

    # ── Ítems ─────────────────────────────────────────────────────────────────
    items_html = ""
    for it in d.get("items", []):
        eje       = esc(it.get("eje", ""))
        titular   = esc(it.get("titular", ""))
        resumen   = esc(it.get("resumen", ""))
        pqi       = esc(it.get("por_que_importa", ""))
        fuente_i  = esc(it.get("fuente", ""))
        fecha_pub = esc(it.get("fecha_publicacion", ""))
        url_i     = esc(it.get("url", ""))
        src_i     = (
            f'<a href="{url_i}" style="color:#1a3a6b;">{fuente_i or url_i}</a>'
            if url_i else fuente_i
        )
        if fecha_pub:
            src_i += f" &middot; <span>{fecha_pub}</span>"
        eje_tag   = (
            f'<div style="font-size:11px;font-weight:700;color:#c59a33;text-transform:uppercase;'
            f'letter-spacing:.08em;margin-bottom:4px;">{eje}</div>'
        ) if eje else ""
        pqi_tag   = (
            f'<div style="margin-top:10px;padding:10px 12px;background:#f0f4fb;border-radius:6px;'
            f'font-size:13px;color:#333;"><b>Por qué importa:</b> {pqi}</div>'
        ) if pqi else ""
        items_html += f"""
      <tr>
        <td style="padding:0 0 20px;">
          <div style="border-left:4px solid #1a3a6b;padding:12px 0 12px 16px;">
            {eje_tag}
            <div style="font-size:16px;font-weight:700;color:#111;margin-bottom:6px;">{titular}</div>
            <div style="font-size:14px;color:#333;line-height:1.6;">{resumen}</div>
            {pqi_tag}
            <div style="margin-top:8px;font-size:12px;color:#666;">Fuente: {src_i}</div>
          </div>
        </td>
      </tr>"""

    # ── Oportunidades ─────────────────────────────────────────────────────────
    opps_html = ""
    for o in d.get("oportunidades", []):
        if isinstance(o, str):
            texto = esc(o); url_o = ""; fuente_o = ""
        else:
            texto    = esc(o.get("texto") or o.get("text", ""))
            url_o    = esc(o.get("url", ""))
            fuente_o = esc(o.get("fuente", ""))
        src_o = (
            f'<a href="{url_o}" style="color:#1a3a6b;font-size:12px;">{fuente_o or url_o}</a>'
            if url_o else
            (f'<span style="font-size:12px;color:#666;">{fuente_o}</span>' if fuente_o else "")
        )
        opps_html += f"""
            <li style="margin-bottom:8px;font-size:13px;color:#333;">
              {texto}{f' <span style="color:#999;">— {src_o}</span>' if src_o else ''}
            </li>"""

    opps_section = ""
    if opps_html:
        opps_section = f"""
      <tr>
        <td style="padding:0 0 24px;">
          <div style="background:#fffbf0;border-radius:8px;padding:16px;">
            <p style="margin:0 0 10px;font-size:13px;font-weight:700;color:#c59a33;
                      text-transform:uppercase;letter-spacing:.05em;">
              Oportunidades accionables
            </p>
            <ul style="margin:0;padding-left:18px;">{opps_html}</ul>
          </div>
        </td>
      </tr>"""

    # ── Ensamblado final ──────────────────────────────────────────────────────
    preheader = subject or titulo

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>{titulo}</title>
</head>
<body style="margin:0;padding:0;background:#f4f6f9;font-family:'Helvetica Neue',Helvetica,Arial,sans-serif;">

  <!-- Preheader (oculto) -->
  <div style="display:none;max-height:0;overflow:hidden;mso-hide:all;">
    {esc(preheader[:150])}
  </div>

  <!-- Wrapper -->
  <table width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#f4f6f9">
    <tr>
      <td align="center" style="padding:24px 12px;">

        <!-- Container 600px -->
        <table width="600" cellpadding="0" cellspacing="0" border="0"
               style="max-width:600px;width:100%;background:#ffffff;border-radius:12px;
                      overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.08);">

          <!-- Cabecera azul -->
          <tr>
            <td style="background:linear-gradient(135deg,#1a3a6b 0%,#2563a8 100%);
                       padding:28px 32px;text-align:center;">
              <div style="font-size:11px;font-weight:700;color:rgba(255,255,255,.65);
                          text-transform:uppercase;letter-spacing:.12em;margin-bottom:6px;">
                Universidad de La Sabana · GovLab
              </div>
              <div style="font-size:24px;font-weight:800;color:#ffffff;line-height:1.25;
                          margin-bottom:8px;">
                {titulo}
              </div>
              <div style="font-size:13px;color:rgba(255,255,255,.75);">
                {fecha}{f' · {contexto}' if contexto else ''}
              </div>
            </td>
          </tr>

          <!-- Cuerpo -->
          <tr>
            <td style="padding:28px 32px;">
              <table width="100%" cellpadding="0" cellspacing="0" border="0">
                {cifras_section}
                {items_html}
                {opps_section}
              </table>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background:#1a3a6b;padding:16px 32px;text-align:center;">
              <div style="font-size:11px;color:rgba(255,255,255,.55);">
                Laboratorio de Gobierno · Universidad de La Sabana<br>
                Este correo fue generado automáticamente por el sistema de newsletter ejecutivo.
              </div>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
