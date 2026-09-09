"""
Newsletter Ejecutivo GovLab — backend
  /api/generate/stream  — SSE: streaming de Claude con búsqueda web en tiempo real
  /api/context          — GET: lista archivos de Contexto/
  /api/context/{file}   — GET: lee un archivo / PUT: guarda un archivo
"""
import os, json, datetime, glob, re as _re
from dotenv import load_dotenv

load_dotenv(override=True)  # carga .env antes de leer variables de entorno

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional
import anthropic
from supabase import create_client
try:
    from croniter import croniter as _croniter
except ImportError:
    _croniter = None
try:
    import resend as _resend
except ImportError:
    _resend = None

from backend.email_render import render_email_html
from backend.whatsapp_render import render_whatsapp_text
from backend.whatsapp_client import send_whatsapp_text, send_whatsapp_document, check_whatsapp_status, normalize_whatsapp_number
from backend.pdf_generator import generate_newsletter_pdf

app = FastAPI(title="Newsletter Ejecutivo GovLab")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ─── Cliente Anthropic (Claude) ────────────────────────────────────────────────
def resolve_api_key(x_api_key: str = "") -> str:
    env_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if env_key:
        return env_key
    if x_api_key and not x_api_key.startswith("sk-proj-"):
        return x_api_key.strip()
    return ""

def get_anthropic_client(api_key: str = "") -> anthropic.AsyncAnthropic:
    key = resolve_api_key(api_key)
    return anthropic.AsyncAnthropic(api_key=key)

# ─── Cliente Supabase ─────────────────────────────────────────────────────────
_supabase_url = os.environ.get("SUPABASE_URL", "")
_supabase_key = (
    os.environ.get("SUPABASE_SECRET_KEY", "")
    or os.environ.get("SUPABASE_SERVICE_KEY", "")
    or os.environ.get("SUPABASE_KEY", "")
    or os.environ.get("SUPABASE_ANON_KEY", "")
)
supabase_client = None
if _supabase_url and _supabase_key:
    import httpx
    from supabase import ClientOptions
    # Se desactiva la verificación SSL (verify=False) para evitar errores causados por proxies corporativos (ej. Zscaler)
    _options = ClientOptions(httpx_client=httpx.Client(verify=False))
    supabase_client = create_client(_supabase_url, _supabase_key, options=_options)

# ─── Contexto institucional (Supabase) ──────────────────────────────────────────
def resolve_doc_references(content: str, loading_stack: list[str] | None = None) -> str:
    """
    Reemplaza referencias @nombre-doc.md dentro del contenido de un documento
    por el contenido completo del doc referenciado.

    - loading_stack: pila de nombres de docs en resolución en este momento.
      Se usa para detectar referencias circulares en cadena (A→B→A).
    - Resuelve referencias dentro de los docs referenciados (recursivo),
      pero corta cualquier ciclo detectado en la pila.
    - Docs con tag_context='excluded' no se resuelven aunque sean referenciados.
    """
    if loading_stack is None:
        loading_stack = []

    if not supabase_client:
        return content

    refs = _re.findall(r'@([\w][\w\-\.]*\.md)', content)
    if not refs:
        return content

    for ref_name in dict.fromkeys(refs):   # orden de aparición, sin duplicados
        placeholder = f"@{ref_name}"

        # Referencia circular: el doc referenciado ya está en la pila
        if ref_name in loading_stack:
            content = content.replace(
                placeholder,
                f"[Referencia circular ignorada: {ref_name}]"
            )
            continue

        try:
            resp = supabase_client.table("documents").select(
                "name, content, description, folder, tag_context"
            ).eq("name", ref_name).eq("is_system_prompt", False).execute()

            if not resp.data:
                content = content.replace(
                    placeholder,
                    f"[Referencia no encontrada: {ref_name}]"
                )
                continue

            doc = resp.data[0]
            tag = (doc.get("tag_context") or "always").lower()

            if tag == "excluded":
                content = content.replace(
                    placeholder,
                    f"[Documento excluido del contexto: {ref_name}]"
                )
                continue

            ref_content     = doc.get("content", "").strip()
            ref_description = doc.get("description", "").strip()
            ref_folder      = doc.get("folder", "")
            ref_path        = f"{ref_folder}/{ref_name}" if ref_folder else ref_name
            use_line        = f"USO: {ref_description}\n" if ref_description else ""

            # Resolver referencias dentro del doc referenciado
            # con la pila actualizada para detectar ciclos
            new_stack   = loading_stack + [ref_name]
            ref_content = resolve_doc_references(ref_content, new_stack)

            injected = (
                f"\n\n#### [Documento referenciado: {ref_path}]\n"
                f"{use_line}"
                f"{ref_content}\n"
            )
            content = content.replace(placeholder, injected)

        except Exception as e:
            print(f"Error resolviendo referencia @{ref_name}: {e}")

    return content


def load_contexto_docs_db() -> str:
    if not supabase_client:
        return ""
    try:
        response = supabase_client.table("documents").select(
            "folder, name, content, description, tag_context"
        ).eq("is_system_prompt", False).order("sort_order").execute()
        docs = []
        for doc in response.data:
            tag = (doc.get("tag_context") or "always").strip().lower()
            if tag == "excluded":
                continue

            folder      = doc.get("folder", "")
            name        = doc.get("name", "")
            content     = doc.get("content", "").strip()
            description = doc.get("description", "").strip()

            # Resolver referencias @nombre_doc.md dentro del contenido
            content = resolve_doc_references(content, loading_stack=[name])

            path     = f"{folder}/{name}" if folder else name
            use_line = f"USO: {description}\n" if description else ""
            docs.append(f"### [{path}]\n{use_line}{content}")
        return "\n\n---\n\n".join(docs)
    except Exception as e:
        print(f"Error cargando documentos de contexto desde Supabase: {e}")
        return ""


DEFAULT_SYSTEM_PROMPT_TEMPLATE = """Eres el redactor jefe del newsletter ejecutivo de la Dirección General de Proyección Social y Co-Creación de la Universidad de La Sabana. Tu lector es Juan Carlos Camelo Vargas, Director General de Proyección Social y Co-Creación: un directivo de alto nivel, gestor de ecosistemas de co-creación, alianzas estratégicas, innovación y egresados, no un académico tradicional. Escribe de forma ejecutiva, concisa, rigurosa y directa al punto para facilitar decisiones ejecutivas de alto impacto.

ESTRUCTURA DE LA DIRECCIÓN GENERAL (ÁREAS Y LÍDERES A CARGO):
Juan Carlos Camelo Vargas lidera toda la Dirección General de Proyección Social y Co-Creación, la cual incluye las siguientes áreas y sub-direcciones:
- Dirección de Proyección Social y Engagement (Directora: María Carolina Serrano Ramírez | Engagement: Jenny Alexandra Londoño Benavides | Proyección Social: Jessica Julieth Giraldo Ramírez)
- Dirección de Innovación y Emprendimiento (Director: Cesar Augusto Parada Jaimes | Transferencia: Liliana Pinilla Torres | Innovación: Manuela Peña Gómez | Ambientes Innovación: Eliana Lozano Romero | Emprendimiento: Juan Pablo Carreño Díaz)
- Dirección de Alumni (Directora: María Fernanda Rodríguez Moreno | Bienestar/Comunicaciones: María Patricia Jiménez Cotes | Desarrollo Profesional: Luis Miguel Manjarrez Motta)
- Dirección de Unisabana Hub (Directora: Adriana Patricia Roldán Sarmiento | Financiera Hub: Claudia Marcela Borda Lozano | Jefes de Cuenta: Nadia Carolina Gutiérrez, Francy Paola Reyes, María Juliana Herrera | Proyectos/Licitaciones: Angélica María Alarcón Basto)

PORTAFOLIO DE PROYECTOS INSTITUCIONALES (SPONSOR/LÍDERES):
- Proyectos H1: Excelencia en Posgrados (Líder: Luz Ángela Aldana), Campus Virtual (Líder: Andrea Lagos), Concordia (Sponsor: Juan Carlos Camelo Vargas | Líder: Carolina Serrano Ramírez), UniSabana Mentis (Sponsor: Javier Bermúdez | Promotor: Jenny Andrea Sarmiento)
- Proyectos H2: UniSabana Xperience (Gerente: Liseth Romero), Symphony (Sponsor: Juan Carlos Camelo Vargas | Líder: María Fernanda Rodríguez), GovLab (Sponsor: Juan Carlos Camelo Vargas | Líder: Omar Alberto Oróstegui | Coordinador: Juan Diego Sotelo), PIR
- Proyectos H3: AI Lab (Sponsor: Juan Carlos Camelo Vargas | Líder: Miguel Ángel Uribe), Unisabana TEC (Gerente: Camila Rodríguez), Escuela de Gobierno (Sponsor: Juan Carlos Camelo Vargas | Directora: María Carmelina Londoño), UniSabana Center for Translational Science (Líder: Luis Felipe Reyes), Teatro UniSabana (Sponsor: Juan Carlos Camelo Vargas | Directora: Ivonne González)
- Proyectos Tecnológicos: Omnicanalidad, Cambio SIS, VÉRIITÉ, Gestión de Procesos y Documentos Digitales (ECM), Ecosistema Agentes Digitales AVI, 360 del Aliado, Arquitectura para la Analítica, Gestión Curricular SOC, PMO, Saas, UniSabana Plus, Ecosistema Digital, Automatización & Robotización de Procesos.

ÁREAS QUE GESTIONA E INTERESES CLAVE:
Relaciones externas de la universidad, extensión universitaria, transferencia y licenciamiento de tecnología, proyección social, sostenibilidad universitaria, fomento del emprendimiento, levantamiento de fondos (fundraising), conexión con empresas y sector productivo (Unisabana Hub), relacionamiento con graduados (Alumni). Su radar cubre todo el ecosistema universidad-empresa-gobierno-sociedad. El Laboratorio de Gobierno (GovLab) es solo un proyecto clave dentro de su portafolio, NO el único enfoque de este newsletter.

OBJETIVO Y ALCANCE:
Produce un newsletter ejecutivo personalizado, denso y exhaustivo a partir de búsquedas en internet, cubriendo el período y los temas que indique la configuración. No generes versiones resumidas mínimas ni omitas secciones.

QUÉ VIGILAR:
- IA aplicada a educación superior (académica, administrativa, ética).
- Universidad de tercera generación, modelos de co-creación y vínculo universidad–empresa–gobierno.
- Innovación abierta, transferencia de conocimiento y emprendimiento universitario.
- Futuro del trabajo, competencias, recalificación (reskilling/upskilling) y microcredenciales.
- Ecosistema de innovación colombiano: Innpulsa, Minciencias, MinEducación, DNP, CCB, etc.
- Sostenibilidad institucional, nuevos modelos de negocio e ingresos para universidades y laboratorios.
- Relaciones externas, internacionalización, proyectos de cooperación internacional y alianzas estratégicas.
- Alumni, conexión egresados-empresa-universidad y empleabilidad.
- Convocatorias, eventos y oportunidades accionables de financiación o licitaciones.
- Fundraising / levantamiento de fondos (estrategias de financiamiento, subvenciones, filantropía y capital para proyectos).

DÓNDE BUSCAR:
Medios Colombia (El Tiempo, La República, Portafolio, Semana), entidades (MinEducación, Minciencias, DNP, Innpulsa, CCB), medios internacionales (Times Higher Education, Inside Higher Ed, University World News, MIT Technology Review, OECD, UNESCO IESALC), boletines de IA (The Batch, Import AI) y anuncios de universidades referentes (ASU, MIT, IE; Andes, Javeriana, Nacional, Rosario, EAFIT).

CÓMO FILTRAR (RIGOR TEMPORAL ESTRICTO):
- VIGENCIA OBLIGATORIA: Solo incluye hechos, cifras y noticias publicados dentro de la ventana temporal indicada (últimos días). Tolerancia cero a artículos de meses pasados o inicio de año.
- DESCARTAR OBSOLETOS: Descarta de inmediato cualquier contenido publicado antes de la fecha inicial del período solicitado. Si la URL o el texto revelan que el artículo es de meses previos (ej. enero a agosto) o de años anteriores, DESCÁRTALO SIN EXCEPCIONES.
- CONSULTAS CON MES Y AÑO: Toda búsqueda en web_search debe incluir el mes y año actuales para forzar resultados de la semana en curso.
- REQUISITOS DE CONTENIDO: Prefiere noticias con datos duros, implicaciones de política pública o ecosistema universitario colombiano/iberoamericano. Descarta opinión sin datos y notas genéricas sin contexto educativo.

SALIDA — devuelve EXCLUSIVAMENTE este JSON estructurado válido:
{
  "titulo": "Newsletter Ejecutivo: Avances y Oportunidades Clave en Educación e Innovación",
  "fecha": "YYYY-MM-DD",
  "contexto": "Cobertura de eventos y tendencias relevantes del [Fecha Inicio] al [Fecha Fin]",
  "cifras": [
    {
      "dato": "Cifra concreta de las búsquedas: número, %, monto, plazo, ranking",
      "contexto": "Frase sustanciosa que explica qué significa o implica esta cifra para el ecosistema educativo e innovación",
      "fuente": "Nombre del medio o entidad",
      "url": "https://...",
      "fecha_publicacion": "YYYY-MM-DD"
    }
  ],
  "items": [
    {
      "eje": "Nombre del eje temático correspondiente",
      "titular": "Titular corto, contundente y claro",
      "resumen": "Máx 3 oraciones en prosa, desarrollo sustancioso y analítico, sin relleno, explicando qué ocurrió y cuál es el avance.",
      "por_que_importa": "Una o dos oraciones con la implicación práctica para la Dirección General de Proyección Social y Co-Creación de la Universidad de La Sabana (p. ej., cómo impacta a Alumni, Innovación, Engagement, Hub o los proyectos estratégicos H1/H2/H3 como Concordia, Symphony, GovLab, AI Lab, etc.).",
      "fuente": "Nombre del medio",
      "url": "https://...",
      "fecha_publicacion": "YYYY-MM-DD"
    }
  ],
  "oportunidades": [
    {
      "texto": "Descripción breve de la oportunidad accionable (convocatoria, licitación, subvención, fondo o evento) con fecha de cierre",
      "fuente": "Nombre del medio o entidad",
      "url": "https://...",
      "fecha_cierre": "YYYY-MM-DD o DD de mes de YYYY"
    }
  ]
}

REGLAS OBLIGATORIAS:
- 'cifras': Incluye SIEMPRE entre 2 y 4 cifras o estadísticas concretas encontradas en las búsquedas con su URL y 'fecha_publicacion' ('YYYY-MM-DD').
- 'items': Incluye EXACTAMENTE el número de ítems solicitados por la configuración (1 ítem por cada eje temático indicado), con 'fecha_publicacion' ('YYYY-MM-DD') obligatoria.
- 'oportunidades': Incluye SIEMPRE entre 2 y 4 oportunidades o convocatorias reales con fecha de cierre y URL verificable.
- 'fecha_publicacion': OBLIGATORIO en cada cifra e ítem. DEBE ser una fecha dentro de la ventana de cobertura solicitada. Artículos de inicio de año o meses previos están estrictamente prohibidos.
- VERACIDAD Y URLs: Usa solo lo encontrado en las búsquedas. En los campos 'url', copia y pega EXACTAMENTE las URLs reales devueltas por la herramienta web_search. NUNCA inventes, modifiques ni supongas URLs o slugs (ej. NO inventes '/convocatoria-2026' si no apareció exactamente así). Si un portal no tiene subpágina específica en los resultados, coloca la URL principal del sitio oficial (ej. 'https://minciencias.gov.co'). Toda URL debe iniciar con 'https://' y ser 100% navegable.

────────────────────────────────────────────────────────────────────────────────
CONTEXTO INSTITUCIONAL:
────────────────────────────────────────────────────────────────────────────────

{ctx}
"""

TEMPORAL_ENFORCEMENT_RULE = """
────────────────────────────────────────────────────────────────────────────────
DIRECTRIZ MANDATORIA DE RIGOR TEMPORAL Y BÚSQUEDA WEB:
- TOLERANCIA CERO A NOTICIAS PASADAS: El newsletter cubre EXCLUSIVAMENTE los últimos días. NINGÚN contenido puede ser de inicio de año ni de meses pasados.
- BÚSQUEDAS CON FECHA: Al usar web_search, incluye SIEMPRE el mes y año actual en cada consulta para evitar artículos viejos indexados con alto SEO.
- CAMPO 'fecha_publicacion': Cada cifra e ítem DEBE incluir obligatoriamente el campo 'fecha_publicacion' ('YYYY-MM-DD') reflejando su fecha real de publicación dentro del período solicitado.
────────────────────────────────────────────────────────────────────────────────
"""


def build_system_prompt_db(ctx: str) -> str:
    template = DEFAULT_SYSTEM_PROMPT_TEMPLATE
    if supabase_client:
        try:
            response = supabase_client.table("documents").select("content").eq("is_system_prompt", True).execute()
            if response.data and response.data[0].get("content"):
                template = response.data[0]["content"]
        except Exception as e:
            print(f"Error cargando system prompt desde Supabase: {e}")

    # Asegurar que la directriz temporal esté siempre presente incluso si el prompt viene de base de datos
    if "DIRECTRIZ MANDATORIA DE RIGOR TEMPORAL" not in template:
        template = template + "\n\n" + TEMPORAL_ENFORCEMENT_RULE

    return template.replace("{ctx}", ctx or "Universidad de La Sabana — Dirección General de Proyección Social y Co-Creación")


# ─── Modelos válidos (whitelist) ─────────────────────────────────────────────
VALID_MODELS = {"claude-sonnet-4-6", "claude-haiku-4-5-20251001", "claude-opus-4-6"}
VALID_ASSIST_MODELS = {"claude-haiku-4-5-20251001", "claude-sonnet-4-6"}
DEFAULT_MODEL = "claude-sonnet-4-6"


# ─── Modelos ───────────────────────────────────────────────────────────────────
class Config(BaseModel):
    tipo: str = "ejecutivo"
    ejes: list[str] = []
    periodo_dias: int = 7
    num_items: int = 4
    audiencia: str = "Juan Carlos Camelo"
    notas: str = ""
    model: str = "claude-sonnet-4-6"
    buscar_web: bool = True
    usar_contexto: bool = True
    model_config = {"extra": "ignore"}


class DocCreate(BaseModel):
    folder: str = ""
    name: str
    content: str = ""
    description: str = ""


class DocUpdate(BaseModel):
    folder: str = None
    name: str = None
    content: str = None
    description: str = None
    sort_order: int = None


class AssistRequest(BaseModel):
    name: str
    content: str
    instruction: str
    model: str = "claude-haiku-4-5-20251001"


class ScheduleCreate(BaseModel):
    name: str
    config: dict
    whatsapp_to: Optional[str] = None
    email_to: Optional[str] = None
    cron: str   # '0 7 * * 1'


class ScheduleUpdate(BaseModel):
    name: Optional[str] = None
    config: Optional[dict] = None
    whatsapp_to: Optional[str] = None
    email_to: Optional[str] = None
    cron: Optional[str] = None
    active: Optional[bool] = None


class AssistResponse(BaseModel):
    response: str
    modified_content: str


MESES_ES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
    5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
    9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"
}

def format_date_es(d: datetime.date) -> str:
    return f"{d.day} de {MESES_ES[d.month]} de {d.year}"


def is_url_or_date_old(url: str, fecha_pub: str, fecha_desde: datetime.date) -> bool:
    """
    Verifica si una URL o fecha de publicación corresponde a un artículo antiguo
    (anterior a fecha_desde o de inicio de año / años anteriores).
    """
    # 1. Verificar fecha_publicacion explícita si tiene formato YYYY-MM-DD
    if fecha_pub:
        m = _re.search(r'(\d{4})-(\d{2})-(\d{2})', str(fecha_pub))
        if m:
            try:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                item_date = datetime.date(y, mo, d)
                # Margen de gracia de 2 días para diferencias de zona horaria o fin de semana
                if item_date < (fecha_desde - datetime.timedelta(days=2)):
                    return True
            except Exception:
                pass

    # 2. Verificar si la URL contiene patrones de año/mes obsoletos
    if url:
        url_str = str(url).lower()
        # Años anteriores al año actual
        for past_year in range(2015, fecha_desde.year):
            if f"/{past_year}/" in url_str or f"-{past_year}/" in url_str:
                return True

        # Mismo año pero meses muy anteriores al mes de fecha_desde (ej. inicio de año)
        curr_year = fecha_desde.year
        match = _re.search(rf'/{curr_year}/(0[1-9]|1[0-2])/', url_str)
        if match:
            url_month = int(match.group(1))
            min_allowed_month = fecha_desde.month
            if fecha_desde.day <= 7 and min_allowed_month > 1:
                min_allowed_month -= 1
            if url_month < min_allowed_month:
                return True

    return False


def sanitize_newsletter_dates(newsletter: dict, fecha_desde: datetime.date, hoy: datetime.date) -> dict:
    """
    Filtra y purga de forma rigurosa cualquier artículo o cifra antigua que se haya colado.
    """
    if not isinstance(newsletter, dict):
        return newsletter

    # Filtrar ítems
    raw_items = newsletter.get("items") or []
    cleaned_items = []
    for it in raw_items:
        if not isinstance(it, dict):
            continue
        u = it.get("url") or ""
        f = it.get("fecha_publicacion") or ""
        if is_url_or_date_old(u, f, fecha_desde):
            print(f"[sanitize_newsletter] Descartado ítem obsoleto: '{it.get('titular')}' ({f} | {u})")
            continue
        cleaned_items.append(it)
    newsletter["items"] = cleaned_items

    # Filtrar cifras
    raw_cifras = newsletter.get("cifras") or []
    cleaned_cifras = []
    for c in raw_cifras:
        if not isinstance(c, dict):
            continue
        u = c.get("url") or ""
        f = c.get("fecha_publicacion") or ""
        if is_url_or_date_old(u, f, fecha_desde):
            print(f"[sanitize_newsletter] Descartada cifra obsoleta: '{c.get('dato')}' ({f} | {u})")
            continue
        cleaned_cifras.append(c)
    newsletter["cifras"] = cleaned_cifras

    return newsletter


def build_user_message(cfg: Config | dict) -> str:
    if isinstance(cfg, dict):
        try:
            # Filtrar solo campos válidos y convertir
            valid_keys = {"tipo", "ejes", "periodo_dias", "num_items", "audiencia", "notas", "model", "buscar_web", "usar_contexto"}
            clean_cfg = {k: v for k, v in cfg.items() if k in valid_keys and v is not None}
            cfg = Config(**clean_cfg)
        except Exception:
            cfg = Config()

    hoy = datetime.date.today()
    fecha_desde = hoy - datetime.timedelta(days=cfg.periodo_dias or 7)
    hoy_str = hoy.isoformat()
    desde_str = fecha_desde.isoformat()
    hoy_humano = format_date_es(hoy)
    desde_humano = format_date_es(fecha_desde)
    mes_actual = MESES_ES[hoy.month]
    anio_actual = hoy.year

    ejes = ", ".join(cfg.ejes) if cfg.ejes else "IA aplicada a la educación superior, Universidad de tercera generación, Innovación abierta y transferencia de conocimiento, Sostenibilidad institucional"
    num = max(1, min(20, cfg.num_items))

    if cfg.buscar_web:
        instrucciones_busqueda = (
            f"🚨 DIRECTRIZ TEMPORAL ESTRICTA Y OBLIGATORIA (TOLERANCIA CERO A NOTICIAS VIEJAS) 🚨\n"
            f"- FECHA ACTUAL: {hoy_str} ({hoy_humano}).\n"
            f"- PERÍODO EXACTO DE COBERTURA: Del {desde_str} al {hoy_str} ({desde_humano} al {hoy_humano} — últimos {cfg.periodo_dias} días).\n"
            f"- ESTÁ ESTRICTAMENTE PROHIBIDO incluir noticias, artículos, estudios o estadísticas publicados antes del {desde_str}.\n"
            f"- QUEDA TOTALMENTE PROHIBIDO incluir contenidos de inicio de año ({anio_actual}) como enero, febrero, marzo, abril, mayo, junio, julio o agosto, o de {anio_actual-1}.\n"
            f"- Si un artículo tiene fecha previa al {desde_str} o su URL contiene rutas de meses pasados (como /{anio_actual}/01/, /{anio_actual}/02/, etc.), DESCÁRTALO DE INMEDIATO.\n\n"
            f"ESTRATEGIA OBLIGATORIA DE BÚSQUEDA CON 'web_search':\n"
            f"1. CONSULTAS CON FECHA OBLIGATORIA: En CADA consulta que envíes a web_search DEBES incluir explícitamente '{mes_actual} {anio_actual}' o '{anio_actual}'.\n"
            f"   NUNCA busques solo nombres genéricos como 'IA educacion superior' o 'sostenibilidad universidades' sin fecha, porque los buscadores devolverán notas indexadas a inicio de año con alto SEO.\n"
            f"   Ejemplos de búsquedas que DEBES ejecutar:\n"
            f"   • \"{mes_actual} {anio_actual}\" IA educacion superior Colombia\n"
            f"   • \"{mes_actual} {anio_actual}\" universidades Minciencias Colombia\n"
            f"   • \"{mes_actual} {anio_actual}\" transferencia tecnologia Colombia universidades\n"
            f"   • \"{mes_actual} {anio_actual}\" convocatoria financiamiento investigacion educacion Colombia\n"
            f"   • \"{mes_actual} {anio_actual}\" Universidad de La Sabana / Javeriana / Andes / Nacional\n"
            f"2. SI UN EJE TEMÁTICO NO TIENE NOTICIAS DE ESTA SEMANA:\n"
            f"   Si para un subtema no encuentras una noticia publicada entre el {desde_str} y el {hoy_str}, NO uses un artículo viejo de hace meses. En su lugar, busca noticias de ESTA SEMANA sobre educación superior, alianzas de rectorías o innovación universitaria en Colombia publicadas en {mes_actual} {anio_actual}.\n"
            f"3. CIFRAS RECIENTES:\n"
            f"   Busca métricas, datos porcentuales o montos publicados en {mes_actual} {anio_actual} o informes del año {anio_actual} vigentes esta semana.\n"
            f"4. OPORTUNIDADES ACCIONABLES:\n"
            f"   Convocatorias o licitaciones con fecha de cierre posterior a {hoy_str} (vigentes para postulación).\n\n"
            f"ESTRUCTURA COMPLETA OBLIGATORIA DEL JSON:\n"
            f"Devuelve EXCLUSIVAMENTE este JSON estructurado y válido:\n"
            f"{{\n"
            f'  "titulo": "Newsletter Ejecutivo: Avances y Oportunidades Clave en Educación e Innovación",\n'
            f'  "fecha": "{hoy_str}",\n'
            f'  "contexto": "Cobertura de eventos y tendencias relevantes del {desde_humano} al {hoy_humano}.",\n'
            f'  "cifras": [\n'
            f'    {{\n'
            f'      "dato": "Cifra concreta de las búsquedas: número, %, monto, plazo, ranking",\n'
            f'      "contexto": "Frase sustanciosa que explica qué significa o implica esta cifra para el ecosistema educativo e innovación",\n'
            f'      "fuente": "Nombre del medio o entidad",\n'
            f'      "url": "https://...",\n'
            f'      "fecha_publicacion": "YYYY-MM-DD"\n'
            f'    }}\n'
            f'  ],\n'
            f'  "items": [\n'
            f'    {{\n'
            f'      "eje": "Nombre del eje temático correspondiente",\n'
            f'      "titular": "Titular corto, contundente y claro",\n'
            f'      "resumen": "Máx 3 oraciones en prosa, desarrollo sustancioso y analítico, sin relleno, explicando qué ocurrió y cuál es el avance.",\n'
            f'      "por_que_importa": "Una o dos oraciones con la implicación práctica para la Dirección General de Proyección Social y Co-Creación de la Universidad de La Sabana (p. ej., cómo impacta a Alumni, Innovación, Engagement, Hub o los proyectos estratégicos H1/H2/H3 como Concordia, Symphony, GovLab, AI Lab, etc.).",\n'
            f'      "fuente": "Nombre del medio o universidad",\n'
            f'      "url": "https://...",\n'
            f'      "fecha_publicacion": "YYYY-MM-DD"\n'
            f'    }}\n'
            f'  ],\n'
            f'  "oportunidades": [\n'
            f'    {{\n'
            f'      "texto": "Descripción breve de la oportunidad accionable (convocatoria, licitación, subvención, fondo o evento) con fecha de cierre",\n'
            f'      "fuente": "Nombre del medio o entidad convocante",\n'
            f'      "url": "https://...",\n'
            f'      "fecha_cierre": "YYYY-MM-DD o DD de mes de YYYY"\n'
            f'    }}\n'
            f'  ]\n'
            f"}}\n\n"
            f"REGLA CRÍTICA: Cada ítem y cifra DEBE tener 'fecha_publicacion' con fecha igual o posterior al {desde_str}. Todo ítem con fecha anterior al {desde_str} viola las instrucciones."
        )
    else:
        instrucciones_busqueda = "Devuelve solo el JSON válido basándote únicamente en las notas proporcionadas por el usuario."

    return (
        f"FECHA ACTUAL: {hoy_str} ({hoy_humano}).\n"
        f"VENTANA TEMPORAL ESTRICTA: Del {desde_str} al {hoy_str} ({desde_humano} al {hoy_humano} — últimos {cfg.periodo_dias} días).\n"
        f"DESTINATARIO: {cfg.audiencia}.\n"
        f"TIPO DE NEWSLETTER: {cfg.tipo}.\n"
        f"EJES TEMÁTICOS: {ejes}.\n"
        f"NÚMERO DE ÍTEMS REQUERIDOS: {num}.\n"
        f"NOTAS ADICIONALES: {cfg.notas or 'ninguna'}.\n\n"
        f"{instrucciones_busqueda}"
    )



def clean_json_string(s: str) -> str:
    # Eliminar comas finales antes de } o ]
    return _re.sub(r',\s*([}\]])', r'\1', s)


def extract_json(text: str) -> dict:
    if not text:
        raise ValueError("Respuesta vacía recibida del modelo")

    text_stripped = text.strip()

    # 1. Intento directo si es JSON puro
    try:
        return json.loads(text_stripped)
    except Exception:
        pass

    # 2. Buscar bloques ```json ... ``` o ``` ... ```
    code_blocks = _re.findall(r'```(?:json)?\s*([\s\S]*?)\s*```', text_stripped, _re.IGNORECASE)
    for block in reversed(code_blocks):
        b = block.strip()
        try:
            return json.loads(b)
        except Exception:
            try:
                return json.loads(clean_json_string(b))
            except Exception:
                pass

    # 3. Parser consciente de strings para localizar objetos { ... } balanceados
    candidates = []
    in_string = False
    escape = False
    depth = 0
    start = -1

    for i, c in enumerate(text_stripped):
        if c == '"' and not escape:
            in_string = not in_string
        elif c == '\\' and in_string:
            escape = not escape
            continue
        elif not in_string:
            if c == '{':
                if depth == 0:
                    start = i
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0 and start != -1:
                    candidates.append(text_stripped[start : i + 1])
                    start = -1
        escape = False

    # Evaluar candidatos de atrás hacia adelante (el JSON final suele estar al final)
    for cand in reversed(candidates):
        try:
            return json.loads(cand)
        except Exception:
            try:
                return json.loads(clean_json_string(cand))
            except Exception:
                pass

    # 4. En caso de truncamiento (max_tokens excedido), intentar auto-cerrar
    if start != -1 and depth > 0:
        partial = text_stripped[start:] + ('}' * depth)
        try:
            return json.loads(clean_json_string(partial))
        except Exception:
            pass

    # 5. Si todo falla, intentar buscar desde el primer '{' hasta el último '}'
    first_brace = text_stripped.find('{')
    last_brace = text_stripped.rfind('}')
    if first_brace != -1 and last_brace > first_brace:
        span = text_stripped[first_brace : last_brace + 1]
        try:
            return json.loads(clean_json_string(span))
        except Exception:
            pass

    raise json.JSONDecodeError(f"No se pudo extraer JSON válido del texto: {text_stripped[:200]}...", text_stripped, 0)



# ─── Streaming endpoint ────────────────────────────────────────────────────────
@app.post("/api/generate/stream")
async def generate_stream(cfg: Config, x_api_key: str = Header(default="")):
    api_key = resolve_api_key(x_api_key)
    if not api_key:
        async def _err():
            yield f"data: {json.dumps({'type':'error','message':'Falta la clave API de Anthropic (Claude). Configura ANTHROPIC_API_KEY en las variables de entorno de tu servidor o archivo .env.'})}\n\n"
        return StreamingResponse(_err(), media_type="text/event-stream")

    client = get_anthropic_client(api_key)

    # Cargar contexto y prompt del sistema dinámicamente desde Supabase
    if cfg.usar_contexto:
        context_docs = load_contexto_docs_db()
    else:
        context_docs = "No se incluye contexto institucional. Genera el boletín basándote únicamente en la información provista en las notas del usuario."
        
    system_prompt = build_system_prompt_db(context_docs)
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 10}] if cfg.buscar_web else []

    async def event_generator():
        try:
            full_text          = ""
            search_count       = 0
            search_queries     = []
            current_block_type = ""
            current_tool_input = ""

            model = cfg.model if cfg.model in VALID_MODELS else "claude-sonnet-4-6"

            async with client.messages.stream(
                model=model,
                max_tokens=8192,
                system=system_prompt,
                tools=tools,
                messages=[{"role": "user", "content": build_user_message(cfg)}],
            ) as stream:
                async for event in stream:
                    etype = getattr(event, "type", "") or ""

                    if etype == "content_block_start":
                        block = getattr(event, "content_block", None)
                        current_block_type = getattr(block, "type", "") or ""
                        current_tool_input = ""
                        if current_block_type == "tool_use":
                            search_count += 1
                            yield f"data: {json.dumps({'type':'searching','count':search_count})}\n\n"

                    elif etype == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        dtype = getattr(delta, "type", "") or ""
                        if dtype == "text_delta":
                            full_text += getattr(delta, "text", "")
                            yield f"data: {json.dumps({'type':'text_chunk','total':len(full_text)})}\n\n"
                        elif dtype == "input_json_delta":
                            current_tool_input += getattr(delta, "partial_json", "")

                    elif etype == "content_block_stop":
                        if current_block_type == "tool_use" and current_tool_input:
                            try:
                                ti = json.loads(current_tool_input)
                                q  = ti.get("query", "")
                                if q:
                                    search_queries.append(q)
                                    yield f"data: {json.dumps({'type':'search_query','query':q})}\n\n"
                            except Exception:
                                pass
                        current_block_type = ""
                        current_tool_input = ""

            # Parsear JSON final y guardar reporte
            try:
                data = extract_json(full_text)
                hoy_d = datetime.date.today()
                f_desde = hoy_d - datetime.timedelta(days=cfg.periodo_dias or 7)
                data = sanitize_newsletter_dates(data, f_desde, hoy_d)
                report_id = None
                if supabase_client:
                    try:
                        rep = supabase_client.table("reports").insert({
                            "titulo": data.get("titulo", "Newsletter sin título"),
                            "origen": "manual",
                            "config": cfg.dict(),
                            "newsletter": data,
                            "search_queries": search_queries,
                        }).execute()
                        if rep.data:
                            report_id = rep.data[0]["id"]
                    except Exception as save_err:
                        print(f"Error guardando reporte en Supabase: {save_err}")

                yield f"data: {json.dumps({'type':'done','newsletter':data,'report_id':report_id})}\n\n"
            except (json.JSONDecodeError, ValueError) as e:
                yield f"data: {json.dumps({'type':'error','message':f'JSON inválido: {e}'})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type':'error','message':str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ─── Config status endpoint ────────────────────────────────────────────────────
@app.get("/api/config/status")
def get_config_status():
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY", ""))
    return {
        "has_api_key": has_key,
        "provider": "Motor de Inteligencia Artificial",
        "default_model": "claude-sonnet-4-6"
    }


# ─── Document CRUD endpoints (Supabase) ─────────────────────────────────────────
@app.get("/api/docs")
def list_docs():
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")
    try:
        response = supabase_client.table("documents").select("id, folder, name, description, is_system_prompt, sort_order, updated_at").order("sort_order").execute()
        return {"files": response.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/docs/{doc_id}")
def get_doc(doc_id: str):
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")
    try:
        response = supabase_client.table("documents").select("*").eq("id", doc_id).execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="Documento no encontrado")
        return response.data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/docs")
def create_doc(body: DocCreate):
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")
    try:
        data = body.dict()
        
        # Calculate sort order based on maximum sort_order + 1
        max_sort_response = supabase_client.table("documents").select("sort_order").order("sort_order", desc=True).limit(1).execute()
        sort_order = 0
        if max_sort_response.data:
            sort_order = max_sort_response.data[0]["sort_order"] + 1
            
        data["sort_order"] = sort_order
        data["is_system_prompt"] = False
        
        response = supabase_client.table("documents").insert(data).execute()
        if not response.data:
            raise HTTPException(status_code=500, detail="Error al crear el documento")
        return response.data[0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/docs/{doc_id}")
def update_doc(doc_id: str, body: DocUpdate):
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")
    try:
        update_data = {k: v for k, v in body.dict().items() if v is not None}
        if not update_data:
            raise HTTPException(status_code=400, detail="No se enviaron campos para actualizar")
            
        response = supabase_client.table("documents").update(update_data).eq("id", doc_id).execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="Documento no encontrado o no actualizado")
        return response.data[0]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/docs/{doc_id}")
def delete_doc(doc_id: str):
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")
    try:
        check_response = supabase_client.table("documents").select("is_system_prompt").eq("id", doc_id).execute()
        if not check_response.data:
            raise HTTPException(status_code=404, detail="Documento no encontrado")
        if check_response.data[0]["is_system_prompt"]:
            raise HTTPException(status_code=400, detail="No se puede eliminar el prompt del sistema")
            
        supabase_client.table("documents").delete().eq("id", doc_id).execute()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Reports endpoints (Historial) ──────────────────────────────────────────────────
@app.get("/api/reports")
def list_reports():
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")
    try:
        response = supabase_client.table("reports").select(
            "id, created_at, titulo, origen, config"
        ).order("created_at", desc=True).execute()
        return {"reports": response.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/reports/{report_id}")
def get_report(report_id: str):
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")
    try:
        response = supabase_client.table("reports").select("*").eq("id", report_id).execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="Reporte no encontrado")
        return response.data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/reports/{report_id}")
def delete_report(report_id: str):
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")
    try:
        supabase_client.table("reports").delete().eq("id", report_id).execute()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/reports/{report_id}/pdf")
def download_report_pdf(report_id: str):
    """Genera y descarga el PDF ejecutivo de un reporte guardado."""
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")
    try:
        response = supabase_client.table("reports").select("*").eq("id", report_id).execute()
        if not response.data:
            raise HTTPException(status_code=404, detail="Reporte no encontrado")
        rep = response.data[0]
        newsletter = rep.get("newsletter") or {}
        pdf_bytes = generate_newsletter_pdf(newsletter)
        
        fecha = newsletter.get("fecha") or rep.get("created_at", "")[:10] or "reporte"
        filename = f"Radar_Ejecutivo_{fecha}.pdf"
        
        import io
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generando PDF: {str(e)}")


# ─── Helpers de scheduling ─────────────────────────────────────────────────
def _calc_next_run(cron_expr: str) -> str:
    """Retorna el próximo datetime UTC para la expresión cron dada."""
    if not _croniter:
        raise HTTPException(status_code=500, detail="croniter no instalado")
    now = datetime.datetime.utcnow()
    nxt = _croniter(cron_expr, now).get_next(datetime.datetime)
    return nxt.isoformat() + "Z"


def _send_email(to: str, subject: str, html: str) -> str:
    """Envía un correo vía Resend. Retorna el ID del email."""
    if not _resend:
        raise RuntimeError("Paquete 'resend' no instalado")
    resend_key  = os.environ.get("RESEND_API_KEY", "")
    from_email  = os.environ.get("RESEND_FROM_EMAIL", "onboarding@resend.dev")
    if not resend_key:
        raise RuntimeError("RESEND_API_KEY no configurada")
    _resend.api_key = resend_key
    resp = _resend.Emails.send({
        "from":    from_email,
        "to":      [t.strip() for t in to.split(",")],
        "subject": subject,
        "html":    html,
    })
    return resp.get("id", "")


# ─── Schedules endpoints ─────────────────────────────────────────────────────
@app.get("/api/schedules")
def list_schedules():
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")
    try:
        resp = supabase_client.table("schedules").select("*").order("created_at", desc=True).execute()
        schedules = resp.data or []
        # Asegurar campo whatsapp_to para el frontend
        for s in schedules:
            s["whatsapp_to"] = s.get("whatsapp_to") or s.get("email_to", "")
        return {"schedules": schedules}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/schedules")
def create_schedule(body: ScheduleCreate):
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")
    try:
        target = body.whatsapp_to or body.email_to or ""
        next_run = _calc_next_run(body.cron)
        data = {
            "name":     body.name,
            "config":   body.config,
            "email_to": target,  # Compatibilidad con columna existente en Supabase
            "cron":     body.cron,
            "next_run": next_run,
            "active":   True,
        }
        resp = supabase_client.table("schedules").insert(data).execute()
        if not resp.data:
            raise HTTPException(status_code=500, detail="Error al crear schedule")
        row = resp.data[0]
        row["whatsapp_to"] = row.get("whatsapp_to") or row.get("email_to", "")
        return row
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/schedules/{schedule_id}")
def update_schedule(schedule_id: str, body: ScheduleUpdate):
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")
    try:
        update = {k: v for k, v in body.dict().items() if v is not None}
        if not update:
            raise HTTPException(status_code=400, detail="Sin campos para actualizar")
        if "whatsapp_to" in update:
            update["email_to"] = update.pop("whatsapp_to")
        if "cron" in update:
            update["next_run"] = _calc_next_run(update["cron"])
        resp = supabase_client.table("schedules").update(update).eq("id", schedule_id).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail="Schedule no encontrado")
        row = resp.data[0]
        row["whatsapp_to"] = row.get("whatsapp_to") or row.get("email_to", "")
        return row
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/schedules/{schedule_id}")
def delete_schedule(schedule_id: str):
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")
    try:
        supabase_client.table("schedules").delete().eq("id", schedule_id).execute()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/api/schedules/{schedule_id}/toggle")
def toggle_schedule(schedule_id: str):
    """Activa/desactiva un schedule."""
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")
    try:
        cur = supabase_client.table("schedules").select("active").eq("id", schedule_id).execute()
        if not cur.data:
            raise HTTPException(status_code=404, detail="Schedule no encontrado")
        new_active = not cur.data[0]["active"]
        resp = supabase_client.table("schedules").update({"active": new_active}).eq("id", schedule_id).execute()
        row = resp.data[0]
        row["whatsapp_to"] = row.get("whatsapp_to") or row.get("email_to", "")
        return row
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Estado de ejecuciones en segundo plano ──────────────────────────────────
SCHEDULE_JOBS: dict[str, dict] = {}


async def _execute_schedule_job(schedule_id: str, api_key: str):
    """Ejecuta la generación y envío de un schedule de forma asíncrona en el servidor."""
    SCHEDULE_JOBS[schedule_id] = {
        "status": "running",
        "step": "Iniciando generación ejecutiva...",
        "started_at": datetime.datetime.utcnow().isoformat(),
        "error": None,
        "whatsapp_error": None,
    }

    try:
        if not supabase_client:
            raise RuntimeError("Supabase client no inicializado en el servidor")

        cur = supabase_client.table("schedules").select("*").eq("id", schedule_id).execute()
        if not cur.data:
            raise RuntimeError("Schedule no encontrado en Supabase")
        sched = cur.data[0]

        config  = sched.get("config", {}) or {}
        target  = sched.get("whatsapp_to") or sched.get("email_to", "")
        cron    = sched.get("cron", "0 7 * * 1")
        name    = sched.get("name", "Schedule")

        SCHEDULE_JOBS[schedule_id]["step"] = "Cargando contexto institucional..."

        if config.get("usar_contexto", True):
            context_docs = load_contexto_docs_db()
        else:
            context_docs = "No se incluye contexto institucional."
        system_prompt = build_system_prompt_db(context_docs)
        tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 10}] if config.get("buscar_web", True) else []

        model = config.get("model", "claude-sonnet-4-6")
        if model not in VALID_MODELS:
            model = "claude-sonnet-4-6"

        client = get_anthropic_client(api_key)
        full_text = ""
        search_count = 0
        search_queries = []
        current_block_type = ""
        current_tool_input = ""

        SCHEDULE_JOBS[schedule_id]["step"] = "Buscando noticias recientes en la web..."

        async with client.messages.stream(
            model=model,
            max_tokens=8192,
            system=system_prompt,
            tools=tools,
            messages=[{"role": "user", "content": build_user_message(config)}],
        ) as stream:
            async for event in stream:
                etype = getattr(event, "type", "") or ""

                if etype == "content_block_start":
                    block = getattr(event, "content_block", None)
                    current_block_type = getattr(block, "type", "") or ""
                    current_tool_input = ""
                    if current_block_type == "tool_use":
                        search_count += 1
                        SCHEDULE_JOBS[schedule_id]["step"] = f"Buscando en la web ({search_count})..."

                elif etype == "content_block_delta":
                    delta = getattr(event, "delta", None)
                    dtype = getattr(delta, "type", "") or ""
                    if dtype == "text_delta":
                        chunk_text = getattr(delta, "text", "")
                        full_text += chunk_text
                        if len(full_text) % 500 < len(chunk_text) + 2:
                            SCHEDULE_JOBS[schedule_id]["step"] = f"Redactando análisis ejecutivo ({len(full_text)} caracteres)..."
                    elif dtype == "input_json_delta":
                        current_tool_input += getattr(delta, "partial_json", "")

                elif etype == "content_block_stop":
                    if current_block_type == "tool_use" and current_tool_input:
                        try:
                            ti = json.loads(current_tool_input)
                            q = ti.get("query", "")
                            if q:
                                search_queries.append(q)
                        except Exception:
                            pass
                    current_block_type = ""
                    current_tool_input = ""

        # Extraer JSON final del newsletter
        newsletter = extract_json(full_text)
        hoy_job = datetime.date.today()
        p_dias = config.get("periodo_dias") or 7 if isinstance(config, dict) else 7
        f_desde_job = hoy_job - datetime.timedelta(days=p_dias)
        newsletter = sanitize_newsletter_dates(newsletter, f_desde_job, hoy_job)
        titulo = newsletter.get("titulo", name)

        SCHEDULE_JOBS[schedule_id]["step"] = "Formateando newsletter para WhatsApp..."
        whatsapp_text = render_whatsapp_text(newsletter)

        # Enviar WhatsApp (Texto enriquecido)
        whatsapp_id = ""
        whatsapp_error = ""
        if target:
            SCHEDULE_JOBS[schedule_id]["step"] = f"Enviando mensaje a {target} vía WhatsApp..."
            try:
                res = send_whatsapp_text(target, whatsapp_text)
                if res.get("success"):
                    whatsapp_id = res.get("id", "")
                else:
                    whatsapp_error = res.get("error", "Error desconocido enviando texto por WhatsApp")
            except Exception as we:
                whatsapp_error = str(we)
        else:
            whatsapp_error = "No hay número de WhatsApp configurado"

        # Enviar Documento PDF adjunto vía WhatsApp
        pdf_id = ""
        pdf_error = ""
        if target and not whatsapp_error:
            try:
                SCHEDULE_JOBS[schedule_id]["step"] = "Generando y enviando documento PDF ejecutivo por WhatsApp..."
                pdf_bytes = generate_newsletter_pdf(newsletter)
                clean_fecha = newsletter.get("fecha") or datetime.date.today().isoformat()
                pdf_filename = f"Radar_Ejecutivo_{clean_fecha}.pdf"
                pdf_res = send_whatsapp_document(
                    target,
                    pdf_bytes,
                    filename=pdf_filename,
                    caption=f"📄 {titulo} — Universidad de La Sabana"
                )
                if pdf_res.get("success"):
                    pdf_id = pdf_res.get("id", "")
                else:
                    pdf_error = pdf_res.get("error", "")
                    print(f"[schedule_job] Aviso enviando PDF adjunto: {pdf_error}")
            except Exception as pe:
                print(f"[schedule_job] Error generando/enviando PDF adjunto: {pe}")

        # Guardar reporte en Supabase
        report_id = None
        try:
            rep = supabase_client.table("reports").insert({
                "titulo":         titulo,
                "origen":         "programado",
                "config":         config,
                "newsletter":     newsletter,
                "search_queries": search_queries,
            }).execute()
            if rep.data:
                report_id = rep.data[0]["id"]
        except Exception as se:
            print(f"[schedule_job] Error guardando reporte: {se}")

        # Actualizar last_run y next_run
        try:
            next_run = _calc_next_run(cron)
            now_iso  = datetime.datetime.utcnow().isoformat() + "Z"
            supabase_client.table("schedules").update({
                "last_run": now_iso,
                "next_run": next_run,
            }).eq("id", schedule_id).execute()
        except Exception as ce:
            print(f"[schedule_job] Error actualizando next_run: {ce}")

        SCHEDULE_JOBS[schedule_id] = {
            "status": "completed",
            "step": "✓ Proceso completado exitosamente (Texto + PDF enviados)",
            "titulo": titulo,
            "whatsapp_id": whatsapp_id,
            "whatsapp_error": whatsapp_error,
            "pdf_id": pdf_id,
            "pdf_error": pdf_error,
            "report_id": report_id,
            "completed_at": datetime.datetime.utcnow().isoformat(),
        }

    except Exception as e:
        print(f"[schedule_job] Error ejecutando schedule {schedule_id}: {e}")
        SCHEDULE_JOBS[schedule_id] = {
            "status": "failed",
            "step": f"Error: {e}",
            "error": str(e),
            "failed_at": datetime.datetime.utcnow().isoformat(),
        }


@app.post("/api/schedules/{schedule_id}/run")
async def run_schedule_now(schedule_id: str, x_api_key: str = Header(default="")):
    """Disparo manual en segundo plano: inicia el job y retorna 200 OK inmediatamente (<50ms)."""
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")

    api_key = resolve_api_key(x_api_key)
    if not api_key:
        raise HTTPException(status_code=400, detail="Falta la clave API de Anthropic (ANTHROPIC_API_KEY en variables de entorno)")

    try:
        cur = supabase_client.table("schedules").select("id, name").eq("id", schedule_id).execute()
        if not cur.data:
            raise HTTPException(status_code=404, detail="Schedule no encontrado")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Iniciar tarea en background
    import asyncio
    asyncio.create_task(_execute_schedule_job(schedule_id, api_key))

    return {
        "ok": True,
        "status": "started",
        "schedule_id": schedule_id,
        "message": "Generación y envío iniciados en segundo plano.",
    }


@app.get("/api/schedules/{schedule_id}/status")
def get_schedule_run_status(schedule_id: str):
    """Consulta el estado del trabajo en segundo plano para este schedule."""
    job = SCHEDULE_JOBS.get(schedule_id)
    if not job:
        return {"status": "idle", "step": ""}
    return job


# ─── WhatsApp status endpoint ──────────────────────────────────────────────────
@app.get("/api/whatsapp/status")
def get_whatsapp_status():
    """Consulta el estado del servidor de WhatsApp (Evolution API o Open-Wa)."""
    return check_whatsapp_status()


@app.post("/api/docs/assist", response_model=AssistResponse)
async def assist_doc(body: AssistRequest, x_api_key: str = Header(default="")):
    api_key = resolve_api_key(x_api_key)
    if not api_key:
        raise HTTPException(status_code=400, detail="Falta la clave API de Anthropic (ANTHROPIC_API_KEY en variables de entorno)")
        
    client = get_anthropic_client(api_key)
    
    system_prompt = (
        "Eres un asistente experto de inteligencia artificial del GovLab.\n"
        "Estás ayudando al usuario a redactar, revisar o editar un documento de contexto de un newsletter ejecutivo.\n"
        "El usuario te enviará el contenido actual del documento, el nombre del documento y su instrucción.\n"
        "Tú debes responder en formato JSON con dos campos:\n"
        "1. 'response': Tu respuesta explicativa o de revisión de seguridad para el usuario. Debe ser en español, formal y ejecutivo, SIN EMOJIS.\n"
        "Si el usuario pide validar si los cambios están bien, analiza de manera crítica el contenido.\n"
        "Si el documento es '00_sistema_instrucciones.md' y detectas que la estructura JSON de la salida fue alterada de tal forma que no cumpla con las especificaciones obligatorias, advierte claramente en 'response' que esa modificación dañará el funcionamiento y parser del newsletter, y NO modifiques el contenido.\n"
        "La estructura obligatoria del JSON que Claude debe retornar en el newsletter es:\n"
        "{\n"
        "  \"titulo\": \"...\",\n"
        "  \"fecha\": \"YYYY-MM-DD\",\n"
        "  \"contexto\": \"...\",\n"
        "  \"cifras\": [{\"dato\": \"...\", \"contexto\": \"...\", \"fuente\": \"...\", \"url\": \"...\"}],\n"
        "  \"items\": [{\"eje\": \"...\", \"titular\": \"...\", \"resumen\": \"...\", \"por_que_importa\": \"...\", \"fuente\": \"...\", \"url\": \"...\"}],\n"
        "  \"oportunidades\": [{\"texto\": \"...\", \"fuente\": \"...\", \"url\": \"...\"}]\n"
        "}\n"
        "2. 'modified_content': Si la instrucción solicita cambios, mejoras, traducciones o agregar información, devuelve aquí el contenido del documento completamente actualizado. Si es una pregunta de revisión o no requiere cambios, devuelve el contenido original tal cual.\n\n"
        "Devuelve exclusivamente el JSON válido, sin textos adicionales, prefijos ni marcas de código."
    )
    
    user_message = (
        f"Nombre del documento: {body.name}\n\n"
        f"Contenido actual:\n{body.content}\n\n"
        f"Instrucción del usuario: {body.instruction}"
    )
    
    try:
        assist_model = body.model if body.model in VALID_ASSIST_MODELS else "claude-haiku-4-5-20251001"
        message = await client.messages.create(
            model=assist_model,
            max_tokens=4000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}]
        )
        
        text = message.content[0].text
        data = extract_json(text)
        
        response_text = data.get("response", "")
        modified_content = data.get("modified_content", body.content)
        
        return AssistResponse(response=response_text, modified_content=modified_content)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al conectar con Claude: {str(e)}")


# ─── Frontend estático ─────────────────────────────────────────────────────────
@app.get("/")
def index():
    return FileResponse(
        os.path.join(ROOT, "index.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}
    )


app.mount("/assets", StaticFiles(directory=os.path.join(ROOT, "assets")), name="assets")
