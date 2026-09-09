"""
backend/pdf_generator.py
Generador de informes en PDF ejecutivos de alta calidad para el boletín de la
Universidad de La Sabana (Dirección General de Proyección Social y Co-Creación).
"""
import io
import re
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib.pagesizes import letter
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    KeepTogether,
    HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfgen import canvas


class NumberedCanvas(canvas.Canvas):
    """Lienzo que calcula automáticamente el número total de páginas (Página X de Y)."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_footer(num_pages)
            super().showPage()
        super().save()

    def draw_footer(self, page_count):
        self.saveState()
        w, h = letter
        margin = 40
        self.setFont('Helvetica', 8)
        self.setFillColor(colors.HexColor('#64748B'))
        
        # Línea separadora de pie de página
        self.setStrokeColor(colors.HexColor('#E2E8F0'))
        self.setLineWidth(0.6)
        self.line(margin, 38, w - margin, 38)
        
        # Texto del pie
        self.drawString(margin, 26, "Universidad de La Sabana — Dirección General de Proyección Social y Co-Creación")
        self.drawRightString(w - margin, 26, f"Página {self._pageNumber} de {page_count}")
        self.restoreState()


def _clean_text(s: object) -> str:
    if s is None:
        return ""
    txt = str(s).strip()
    return re.sub(r'\s+', ' ', txt)


def _safe_xml(s: object) -> str:
    """Escapa caracteres especiales para el motor XML de ReportLab."""
    return xml_escape(_clean_text(s))


def _clean_url(url: object) -> str:
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


def generate_newsletter_pdf(newsletter: dict) -> bytes:
    """
    Genera un archivo PDF ejecutivo en memoria a partir del JSON estructurado del newsletter.
    Retorna los bytes del PDF generado.
    """
    d = newsletter if isinstance(newsletter, dict) else {}

    titulo = _clean_text(d.get("titulo") or d.get("title") or "Newsletter Ejecutivo: Avances y Oportunidades Clave")
    fecha = _clean_text(d.get("fecha") or d.get("date") or "")
    contexto = _clean_text(d.get("contexto") or d.get("descripcion") or "")

    buffer = io.BytesIO()
    
    # Márgenes de 40 pt (~1.4 cm) para aprovechar el espacio con estética ejecutiva
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=40,
        rightMargin=40,
        topMargin=36,
        bottomMargin=48
    )

    usable_width = letter[0] - 80  # 612 - 80 = 532 pt

    # ── Paleta de Colores Institucional Unisabana ────────────────────────────
    NAVY = colors.HexColor('#002B49')       # Azul institucional Sabana
    WINE = colors.HexColor('#A6192E')       # Vinotinto / Borgoña institucional
    GOLD = colors.HexColor('#B8860B')       # Acento dorado ejecutivo
    DARK = colors.HexColor('#0F172A')       # Texto principal pizarra oscura
    SLATE = colors.HexColor('#475569')      # Texto secundario
    LIGHT_BG = colors.HexColor('#F8FAFC')   # Fondo sutil tarjetas
    BLUE_BG = colors.HexColor('#EFF6FF')    # Fondo callouts "Por qué importa"
    BLUE_BORDER = colors.HexColor('#2563EB')# Borde callouts
    BORDER = colors.HexColor('#CBD5E1')     # Bordes generales

    # ── Estilos de Tipografía ────────────────────────────────────────────────
    styles = getSampleStyleSheet()

    style_inst = ParagraphStyle(
        'HeaderInstitution',
        fontName='Helvetica-Bold',
        fontSize=8.5,
        leading=11,
        textColor=NAVY,
        textTransform='uppercase',
        spaceAfter=2
    )

    style_subinst = ParagraphStyle(
        'HeaderSubinst',
        fontName='Helvetica',
        fontSize=8,
        leading=10,
        textColor=WINE,
        spaceAfter=6
    )

    style_title = ParagraphStyle(
        'ExecutiveTitle',
        fontName='Helvetica-Bold',
        fontSize=17,
        leading=21,
        textColor=NAVY,
        spaceAfter=6
    )

    style_meta = ParagraphStyle(
        'ExecutiveMeta',
        fontName='Helvetica',
        fontSize=8.5,
        leading=12,
        textColor=SLATE,
        spaceAfter=14
    )

    style_sec_header = ParagraphStyle(
        'SectionHeader',
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=15,
        textColor=NAVY,
        spaceBefore=8,
        spaceAfter=8
    )

    style_cifra_dato = ParagraphStyle(
        'CifraDato',
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=15,
        textColor=WINE,
        spaceAfter=3
    )

    style_cifra_ctx = ParagraphStyle(
        'CifraContexto',
        fontName='Helvetica',
        fontSize=8.5,
        leading=11.5,
        textColor=DARK,
        spaceAfter=3
    )

    style_eje_badge = ParagraphStyle(
        'EjeBadge',
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=NAVY,
        spaceAfter=3
    )

    style_titular = ParagraphStyle(
        'ItemTitular',
        fontName='Helvetica-Bold',
        fontSize=10.5,
        leading=13.5,
        textColor=NAVY,
        spaceAfter=4
    )

    style_resumen = ParagraphStyle(
        'ItemResumen',
        fontName='Helvetica',
        fontSize=8.5,
        leading=12,
        textColor=DARK,
        spaceAfter=5
    )

    style_pqi = ParagraphStyle(
        'ItemPQI',
        fontName='Helvetica',
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor('#1E3A8A'),
        spaceAfter=3
    )

    style_fuente = ParagraphStyle(
        'ItemFuente',
        fontName='Helvetica',
        fontSize=7.8,
        leading=10,
        textColor=colors.HexColor('#2563EB')
    )

    style_opp_text = ParagraphStyle(
        'OppText',
        fontName='Helvetica',
        fontSize=8.5,
        leading=12,
        textColor=DARK
    )

    story = []

    # ── 1. Cabecera Institucional ────────────────────────────────────────────
    story.append(Paragraph("UNIVERSIDAD DE LA SABANA", style_inst))
    story.append(Paragraph("DIRECCIÓN GENERAL DE PROYECCIÓN SOCIAL Y CO-CREACIÓN", style_subinst))
    story.append(Paragraph(_safe_xml(titulo), style_title))

    meta_str = ""
    if fecha and contexto:
        meta_str = f"<b>Edición:</b> {_safe_xml(fecha)} &nbsp;|&nbsp; <b>Alcance:</b> {_safe_xml(contexto)}"
    elif fecha:
        meta_str = f"<b>Edición:</b> {_safe_xml(fecha)}"
    elif contexto:
        meta_str = f"<b>Alcance:</b> {_safe_xml(contexto)}"
    
    if meta_str:
        story.append(Paragraph(meta_str, style_meta))

    story.append(HRFlowable(width="100%", thickness=1.5, color=NAVY, spaceAfter=12))

    # ── 2. Cifras importantes del sector ─────────────────────────────────────
    cifras = d.get("cifras") or d.get("estadisticas") or []
    if cifras:
        story.append(Paragraph("Cifras Importantes del Sector", style_sec_header))
        
        cifra_cells = []
        for c in cifras:
            if isinstance(c, str):
                cell_content = [Paragraph(f"<b>{_safe_xml(c)}</b>", style_cifra_ctx)]
            elif isinstance(c, dict):
                dato = _safe_xml(c.get("dato") or c.get("cifra") or "")
                ctx_c = _safe_xml(c.get("contexto") or c.get("descripcion") or "")
                fuente = _safe_xml(c.get("fuente") or c.get("medio") or "")
                url_c = _clean_url(c.get("url") or c.get("link") or "")

                cell_flow = []
                if dato:
                    cell_flow.append(Paragraph(dato, style_cifra_dato))
                if ctx_c:
                    cell_flow.append(Paragraph(ctx_c, style_cifra_ctx))
                fecha_pub = _safe_xml(c.get("fecha_publicacion") or "")
                fuente_txt = f"Fuente: {fuente}" + (f" ({fecha_pub})" if fecha_pub else "")
                if fuente and url_c:
                    cell_flow.append(Paragraph(f'<a href="{url_c}"><u>{fuente_txt} ↗</u></a>', style_fuente))
                elif url_c:
                    cell_flow.append(Paragraph(f'<a href="{url_c}"><u>Ver enlace {f"({fecha_pub}) " if fecha_pub else ""}↗</u></a>', style_fuente))
                elif fuente:
                    cell_flow.append(Paragraph(f"<i>{fuente_txt}</i>", style_fuente))
                cell_content = cell_flow
            else:
                continue

            # Encapsular cada celda en una tabla estilizada
            card_table = Table(
                [[cell_content]],
                colWidths=[usable_width],
                style=TableStyle([
                    ('BACKGROUND', (0, 0), (-1, -1), LIGHT_BG),
                    ('BOX', (0, 0), (-1, -1), 0.5, BORDER),
                    ('LEFTPADDING', (0, 0), (-1, -1), 8),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                    ('TOPPADDING', (0, 0), (-1, -1), 6),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                ])
            )
            story.append(card_table)
            story.append(Spacer(1, 6))

        story.append(Spacer(1, 8))

    # ── 3. Ítems Principales por Eje Temático ────────────────────────────────
    items = d.get("items") or d.get("noticias") or d.get("articulos") or []
    if items:
        story.append(Paragraph("Avances y Noticias Estratégicas por Eje", style_sec_header))

        for it in items:
            if not isinstance(it, dict):
                continue
            eje = _safe_xml(it.get("eje") or it.get("categoria") or "")
            titular = _safe_xml(it.get("titular") or it.get("titulo") or "")
            resumen = _safe_xml(it.get("resumen") or it.get("contenido") or "")
            pqi = _safe_xml(it.get("por_que_importa") or it.get("importancia") or "")
            fuente_i = _safe_xml(it.get("fuente") or "")
            url_i = _clean_url(it.get("url") or it.get("link") or "")

            item_elements = []

            # Badge de eje temático
            if eje:
                item_elements.append(Paragraph(f"• EJE: {eje.upper()}", style_eje_badge))
            
            # Titular
            if titular and url_i:
                item_elements.append(Paragraph(f'<a href="{url_i}"><u>{titular}</u></a>', style_titular))
            elif titular:
                item_elements.append(Paragraph(titular, style_titular))

            # Resumen analítico
            if resumen:
                item_elements.append(Paragraph(resumen, style_resumen))

            # Bloque destacado "Por qué importa"
            if pqi:
                pqi_content = [
                    Paragraph(f"<b>Por qué importa para La Sabana:</b> {pqi}", style_pqi)
                ]
                pqi_box = Table(
                    [[pqi_content]],
                    colWidths=[usable_width - 16],
                    style=TableStyle([
                        ('BACKGROUND', (0, 0), (-1, -1), BLUE_BG),
                        ('LINELEFT', (0, 0), (0, 0), 2.5, BLUE_BORDER),
                        ('TOPPADDING', (0, 0), (-1, -1), 5),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                        ('LEFTPADDING', (0, 0), (-1, -1), 8),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                    ])
                )
                item_elements.append(pqi_box)
                item_elements.append(Spacer(1, 4))

            # Enlace de fuente
            fecha_pub = _safe_xml(it.get("fecha_publicacion") or "")
            fuente_txt = f"Fuente: {fuente_i}" + (f" ({fecha_pub})" if fecha_pub else "")
            if fuente_i and url_i:
                item_elements.append(Paragraph(f'<a href="{url_i}"><u>{fuente_txt} ({url_i}) ↗</u></a>', style_fuente))
            elif url_i:
                item_elements.append(Paragraph(f'<a href="{url_i}"><u>Enlace{f" ({fecha_pub})" if fecha_pub else ""}: {url_i} ↗</u></a>', style_fuente))
            elif fuente_i:
                item_elements.append(Paragraph(f"<i>{fuente_txt}</i>", style_fuente))

            # Envolver el ítem completo en una tarjeta
            card_item = Table(
                [[item_elements]],
                colWidths=[usable_width],
                style=TableStyle([
                    ('BACKGROUND', (0, 0), (-1, -1), colors.white),
                    ('BOX', (0, 0), (-1, -1), 0.5, BORDER),
                    ('LEFTPADDING', (0, 0), (-1, -1), 10),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 10),
                    ('TOPPADDING', (0, 0), (-1, -1), 8),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ])
            )

            story.append(KeepTogether([card_item, Spacer(1, 8)]))

    # ── 4. Oportunidades Accionables y Convocatorias ─────────────────────────
    opps = d.get("oportunidades") or d.get("convocatorias") or []
    if opps:
        story.append(Spacer(1, 4))
        story.append(Paragraph("Oportunidades Accionables y Convocatorias", style_sec_header))

        opp_rows = []
        for o in opps:
            if isinstance(o, str):
                opp_rows.append([Paragraph(f"• {_safe_xml(o)}", style_opp_text)])
            elif isinstance(o, dict):
                texto = _safe_xml(o.get("texto") or o.get("text") or o.get("descripcion") or "")
                fuente_o = _safe_xml(o.get("fuente") or "")
                url_o = _clean_url(o.get("url") or o.get("link") or "")

                link_html = ""
                if fuente_o and url_o:
                    link_html = f' &nbsp;—&nbsp; <a href="{url_o}"><u><b>{fuente_o} ↗</b></u></a>'
                elif url_o:
                    link_html = f' &nbsp;—&nbsp; <a href="{url_o}"><u><b>Ver convocatoria ↗</b></u></a>'
                elif fuente_o:
                    link_html = f' &nbsp;—&nbsp; <i>{fuente_o}</i>'

                opp_rows.append([Paragraph(f"• {texto}{link_html}", style_opp_text)])

        if opp_rows:
            opp_table = Table(
                opp_rows,
                colWidths=[usable_width],
                style=TableStyle([
                    ('BACKGROUND', (0, 0), (-1, -1), LIGHT_BG),
                    ('BOX', (0, 0), (-1, -1), 0.5, BORDER),
                    ('LEFTPADDING', (0, 0), (-1, -1), 8),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                    ('TOPPADDING', (0, 0), (-1, -1), 6),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
                    ('LINEBELOW', (0, 0), (-1, -2), 0.5, colors.HexColor('#E2E8F0')),
                ])
            )
            story.append(KeepTogether([opp_table]))

    # Construir el documento PDF con numeración de páginas
    doc.build(story, canvasmaker=NumberedCanvas)
    
    return buffer.getvalue()
