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
import openai
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
from backend.whatsapp_client import send_whatsapp_text, check_whatsapp_status, normalize_whatsapp_number
from backend.web_search import perform_web_search, format_search_results_for_llm

app = FastAPI(title="Newsletter Ejecutivo GovLab")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ─── Clientes OpenAI ──────────────────────────────────────────────────────────
def resolve_api_key(x_api_key: str = "") -> str:
    env_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if env_key:
        return env_key
    if x_api_key and not x_api_key.startswith("sk-ant-"):
        return x_api_key.strip()
    return ""

def get_openai_client(api_key: str = "") -> openai.AsyncOpenAI:
    key = resolve_api_key(api_key)
    return openai.AsyncOpenAI(api_key=key)

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


def build_system_prompt_db(ctx: str) -> str:
    if not supabase_client:
        return f"Eres el redactor del newsletter ejecutivo. Contexto institucional:\n\n{ctx}"
    try:
        response = supabase_client.table("documents").select("content").eq("is_system_prompt", True).execute()
        if response.data:
            template = response.data[0]["content"]
            return template.replace("{ctx}", ctx)
    except Exception as e:
        print(f"Error cargando system prompt desde Supabase: {e}")
    
    return f"Eres el redactor del newsletter ejecutivo. Contexto institucional:\n\n{ctx}"


# ─── Modelos válidos (whitelist) ─────────────────────────────────────────────
VALID_MODELS = {"gpt-4o", "gpt-4o-mini", "o3-mini", "o1-mini", "claude-sonnet-4-6"}
VALID_ASSIST_MODELS = {"gpt-4o", "gpt-4o-mini", "o3-mini", "o1-mini"}
DEFAULT_MODEL = "gpt-4o"

WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Busca noticias, convocatorias, datos y artículos recientes en internet para el boletín ejecutivo.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Término de búsqueda optimizado para encontrar noticias o información reciente"
                }
            },
            "required": ["query"]
        }
    }
}


# ─── Modelos ───────────────────────────────────────────────────────────────────
class Config(BaseModel):
    tipo: str = "ejecutivo"
    ejes: list[str] = []
    periodo_dias: int = 7
    num_items: int = 4
    audiencia: str = "Juan Carlos Camelo"
    notas: str = ""
    model: str = "gpt-4o"
    buscar_web: bool = True
    usar_contexto: bool = True


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
    model: str = "gpt-4o"


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


def build_user_message(cfg: Config | dict) -> str:
    if isinstance(cfg, dict):
        cfg = Config(**cfg)

    hoy = datetime.date.today()
    fecha_desde = hoy - datetime.timedelta(days=cfg.periodo_dias)
    hoy_str = hoy.isoformat()
    desde_str = fecha_desde.isoformat()
    hoy_humano = format_date_es(hoy)
    desde_humano = format_date_es(fecha_desde)
    mes_actual = MESES_ES[hoy.month]
    anio_actual = hoy.year

    ejes = ", ".join(cfg.ejes) if cfg.ejes else "todos los ejes prioritarios"
    num = max(1, min(20, cfg.num_items))

    if cfg.buscar_web:
        instrucciones_busqueda = (
            f"INSTRUCCIONES OBLIGATORIAS DE BÚSQUEDA Y FILTRADO TEMPORAL:\n"
            f"1. RANGO DE FECHAS ESTRICTO: Solo se admiten noticias e información publicadas entre el {desde_str} y el {hoy_str} ({desde_humano} a {hoy_humano}).\n"
            f"2. ESTRATEGIA DE BÚSQUEDA: Al hacer consultas con la herramienta web_search, incluye SIEMPRE términos temporales explícitos (ej. '{mes_actual} {anio_actual}', '{anio_actual}') para asegurar que los motores de búsqueda devuelvan noticias recientes y no artículos antiguos.\n"
            f"3. PROHIBICIÓN ESTRICTA DE NOTICIAS ANTIGUAS: Queda TERMINANTEMENTE PROHIBIDO incluir artículos de meses anteriores (ej. mayo, junio, julio o anteriores) o de fechas fuera del período de los últimos {cfg.periodo_dias} días. Si un artículo encontrado no es reciente o no tiene fecha verificable dentro de la ventana {desde_str} a {hoy_str}, DESCÁRTALO de inmediato y realiza otra búsqueda más precisa.\n"
            f"4. CAMPO 'fecha_publicacion': En cada elemento de 'items' y 'cifras', incluye el campo 'fecha_publicacion' con la fecha exacta (YYYY-MM-DD o DD de Mes) confirmada de la publicación.\n"
            f"Devuelve exclusivamente el JSON estructurado con información real y verificada."
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

    for i, ch in enumerate(text_stripped):
        if in_string:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == '{':
                if depth == 0:
                    start = i
                depth += 1
            elif ch == '}':
                if depth > 0:
                    depth -= 1
                    if depth == 0 and start != -1:
                        candidates.append(text_stripped[start : i + 1])
                        start = -1

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
        partial = text_stripped[start:]
        if in_string:
            partial += '"'
        partial += '}' * depth
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
            yield f"data: {json.dumps({'type':'error','message':'Falta la clave API de OpenAI. Configura OPENAI_API_KEY en las variables de entorno de tu servidor o archivo .env.'})}\n\n"
        return StreamingResponse(_err(), media_type="text/event-stream")

    client = get_openai_client(api_key)

    # Cargar contexto y prompt del sistema dinámicamente desde Supabase
    if cfg.usar_contexto:
        context_docs = load_contexto_docs_db()
    else:
        context_docs = "No se incluye contexto institucional. Genera el boletín basándote únicamente en la información provista en las notas del usuario."
        
    system_prompt = build_system_prompt_db(context_docs)

    async def event_generator():
        try:
            full_text      = ""
            search_count   = 0
            search_queries = []

            # Mapeo de modelo: siempre asegurar el mejor modelo de OpenAI (gpt-4o)
            model = cfg.model if cfg.model in VALID_MODELS else "gpt-4o"
            if "claude" in model.lower():
                model = "gpt-4o"

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": build_user_message(cfg)}
            ]

            tools = [WEB_SEARCH_TOOL] if cfg.buscar_web else None

            # 1. Ronda interactiva de búsqueda web
            max_search_rounds = 3
            round_idx = 0

            while cfg.buscar_web and round_idx < max_search_rounds:
                round_idx += 1
                completion = await client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    temperature=0.7,
                )
                msg = completion.choices[0].message
                tool_calls = getattr(msg, "tool_calls", None)

                if not tool_calls:
                    # El modelo consideró que no necesita más búsquedas
                    break

                messages.append(msg)

                for tc in tool_calls:
                    if tc.function.name == "web_search":
                        search_count += 1
                        yield f"data: {json.dumps({'type':'searching','count':search_count})}\n\n"

                        try:
                            args = json.loads(tc.function.arguments)
                            q = args.get("query", "")
                        except Exception:
                            q = tc.function.arguments or ""

                        if q:
                            search_queries.append(q)
                            yield f"data: {json.dumps({'type':'search_query','query':q})}\n\n"
                            raw_results = perform_web_search(q, max_results=5)
                            content_str = format_search_results_for_llm(raw_results)
                        else:
                            content_str = "No se proporcionó término de búsqueda."

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": content_str
                        })

            # 2. Generación en streaming del texto estructurado del newsletter
            stream = await client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
                temperature=0.7,
            )

            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    full_text += delta.content
                    yield f"data: {json.dumps({'type':'text_chunk','total':len(full_text)})}\n\n"

            # 3. Parsear JSON final y guardar reporte
            try:
                data = extract_json(full_text)
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
    has_key = bool(os.environ.get("OPENAI_API_KEY", ""))
    return {
        "has_api_key": has_key,
        "provider": "OpenAI",
        "default_model": "gpt-4o"
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


@app.post("/api/schedules/{schedule_id}/run")
async def run_schedule_now(schedule_id: str, x_api_key: str = Header(default="")):
    """Disparo manual: genera el newsletter, lo envía por WhatsApp y registra reporte con origen='programado'."""
    if not supabase_client:
        raise HTTPException(status_code=500, detail="Supabase client not initialized")
    try:
        cur = supabase_client.table("schedules").select("*").eq("id", schedule_id).execute()
        if not cur.data:
            raise HTTPException(status_code=404, detail="Schedule no encontrado")
        sched = cur.data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    api_key = resolve_api_key(x_api_key)
    if not api_key:
        raise HTTPException(status_code=400, detail="Falta la clave API de OpenAI (OPENAI_API_KEY en variables de entorno)")

    config  = sched.get("config", {})
    target  = sched.get("whatsapp_to") or sched.get("email_to", "")
    cron    = sched.get("cron", "0 7 * * 1")
    name    = sched.get("name", "Schedule")

    # Generar newsletter
    try:
        from backend.run_due import generate_once as _gen
        newsletter, queries = await _gen(config, api_key=api_key)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generando newsletter: {e}")

    titulo = newsletter.get("titulo", name)
    whatsapp_text = render_whatsapp_text(newsletter)

    # Enviar WhatsApp vía Open-Wa
    whatsapp_id = ""
    whatsapp_error = ""
    if target:
        try:
            res = send_whatsapp_text(target, whatsapp_text)
            if res.get("success"):
                whatsapp_id = res.get("id", "")
            else:
                whatsapp_error = res.get("error", "Error desconocido enviando por WhatsApp")
                print(f"[run_now] Error enviando WhatsApp: {whatsapp_error}")
        except Exception as e:
            whatsapp_error = str(e)
            print(f"[run_now] Excepción enviando WhatsApp: {e}")
    else:
        whatsapp_error = "No hay número de WhatsApp configurado"

    # Guardar reporte
    report_id = None
    try:
        rep = supabase_client.table("reports").insert({
            "titulo":         titulo,
            "origen":         "programado",
            "config":         config,
            "newsletter":     newsletter,
            "search_queries": queries,
        }).execute()
        if rep.data:
            report_id = rep.data[0]["id"]
    except Exception as e:
        print(f"[run_now] Error guardando reporte: {e}")

    # Actualizar next_run
    try:
        next_run = _calc_next_run(cron)
        now_iso  = datetime.datetime.utcnow().isoformat() + "Z"
        supabase_client.table("schedules").update({
            "last_run": now_iso,
            "next_run": next_run,
        }).eq("id", schedule_id).execute()
    except Exception as e:
        print(f"[run_now] Error actualizando next_run: {e}")

    return {
        "ok":             True,
        "report_id":      report_id,
        "whatsapp_id":    whatsapp_id,
        "whatsapp_error": whatsapp_error,
        "titulo":         titulo,
    }


# ─── WhatsApp status endpoint ──────────────────────────────────────────────────
@app.get("/api/whatsapp/status")
def get_whatsapp_status():
    """Consulta el estado del servidor de WhatsApp (Evolution API o Open-Wa)."""
    return check_whatsapp_status()


@app.post("/api/docs/assist", response_model=AssistResponse)
async def assist_doc(body: AssistRequest, x_api_key: str = Header(default="")):
    api_key = resolve_api_key(x_api_key)
    if not api_key:
        raise HTTPException(status_code=400, detail="Falta la clave API de OpenAI (OPENAI_API_KEY en variables de entorno)")
        
    client = get_openai_client(api_key)
    
    system_prompt = (
        "Eres un asistente experto de inteligencia artificial del GovLab.\n"
        "Estás ayudando al usuario a redactar, revisar o editar un documento de contexto de un newsletter ejecutivo.\n"
        "El usuario te enviará el contenido actual del documento, el nombre del documento y su instrucción.\n"
        "Tú debes responder en formato JSON con dos campos:\n"
        "1. 'response': Tu respuesta explicativa o de revisión de seguridad para el usuario. Debe ser en español, formal y ejecutivo, SIN EMOJIS.\n"
        "Si el usuario pide validar si los cambios están bien, analiza de manera crítica el contenido.\n"
        "Si el documento es '00_sistema_instrucciones.md' y detectas que la estructura JSON de la salida fue alterada de tal forma que no cumpla con las especificaciones obligatorias, advierte claramente en 'response' que esa modificación dañará el funcionamiento y parser del newsletter, y NO modifiques el contenido.\n"
        "La estructura obligatoria del JSON del newsletter es:\n"
        "{\n"
        "  \"titulo\": \"...\",\n"
        "  \"fecha\": \"YYYY-MM-DD\",\n"
        "  \"contexto\": \"...\",\n"
        "  \"cifras\": [{\"dato\": \"...\", \"contexto\": \"...\", \"fuente\": \"...\", \"url\": \"...\"}],\n"
        "  \"items\": [{\"eje\": \"...\", \"titular\": \"...\", \"resumen\": \"...\", \"por_que_importa\": \"...\", \"fuente\": \"...\", \"url\": \"...\"}],\n"
        "  \"oportunidades\": [{\"texto\": \"...\", \"fuente\": \"...\", \"url\": \"...\"}]\n"
        "}\n"
        "2. 'modified_content': Si la instrucción solicita cambios, mejoras, traducciones o agregar información, devuelve aquí el contenido del documento completamente actualizado. Si es una pregunta de revisión o no requiere cambios, devuelve el contenido original tal cual.\n\n"
        "Devuelve exclusivamente un objeto JSON válido con las claves 'response' y 'modified_content'."
    )
    
    user_message = (
        f"Nombre del documento: {body.name}\n\n"
        f"Contenido actual:\n{body.content}\n\n"
        f"Instrucción del usuario: {body.instruction}"
    )
    
    try:
        assist_model = body.model if body.model in VALID_ASSIST_MODELS else "gpt-4o"
        if "claude" in assist_model.lower():
            assist_model = "gpt-4o"

        completion = await client.chat.completions.create(
            model=assist_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            response_format={"type": "json_object"},
            temperature=0.3
        )
        
        text = completion.choices[0].message.content or "{}"
        data = extract_json(text)
        
        response_text = data.get("response", "")
        modified_content = data.get("modified_content", body.content)
        
        return AssistResponse(response=response_text, modified_content=modified_content)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al conectar con OpenAI: {str(e)}")


# ─── Frontend estático ─────────────────────────────────────────────────────────
@app.get("/")
def index():
    return FileResponse(
        os.path.join(ROOT, "index.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}
    )


app.mount("/assets", StaticFiles(directory=os.path.join(ROOT, "assets")), name="assets")
