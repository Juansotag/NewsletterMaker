"""
backend/run_due.py
Script de Cron Job para Railway: genera y envía los newsletters programados cuyo next_run ya venció.

Uso:
  python -m backend.run_due

Railway Cron Job: configurar en el dashboard de Railway con el comando anterior, cada 15 min:
  Schedule: */15 * * * *
  Command:  python -m backend.run_due
"""
import os, json, asyncio, datetime
from dotenv import load_dotenv

load_dotenv(override=True)

import httpx
import anthropic
from supabase import create_client, ClientOptions
from croniter import croniter

from backend.email_render import render_email_html
from backend.main import resolve_doc_references, extract_json, build_user_message


# ── Clientes ──────────────────────────────────────────────────────────────────
_supabase_url = os.environ.get("SUPABASE_URL", "")
_supabase_key = (
    os.environ.get("SUPABASE_SECRET_KEY", "")
    or os.environ.get("SUPABASE_SERVICE_KEY", "")
)
_options = ClientOptions(httpx_client=httpx.Client(verify=False))
supabase = create_client(_supabase_url, _supabase_key, options=_options) if (_supabase_url and _supabase_key) else None

_anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
_resend_key    = os.environ.get("RESEND_API_KEY", "")
_from_email    = os.environ.get("RESEND_FROM_EMAIL", "onboarding@resend.dev")


# ── Generación sin streaming ──────────────────────────────────────────────────
async def generate_once(config: dict, api_key: str = "") -> tuple[dict, list[str]]:
    """
    Genera el newsletter completo sin streaming.
    Retorna (newsletter_json, search_queries).
    """
    import re as _re

    # Leer la clave en el momento de la llamada (no en import)
    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise ValueError("ANTHROPIC_API_KEY no configurada")

    client = anthropic.AsyncAnthropic(
        api_key=key,
        http_client=httpx.AsyncClient(verify=False),
    )

    # System prompt
    try:
        sys_resp = supabase.table("documents").select("content").eq("is_system_prompt", True).execute()
        sp_template = sys_resp.data[0]["content"] if sys_resp.data else "{ctx}"
    except Exception:
        sp_template = "{ctx}"

    try:
        ctx_resp = supabase.table("documents").select(
            "folder, name, content, description, tag_context"
        ).eq("is_system_prompt", False).order("sort_order").execute()
        docs = []
        for doc in ctx_resp.data:
            tag = (doc.get("tag_context") or "always").strip().lower()
            if tag == "excluded":
                continue
            folder = doc.get("folder", "")
            name   = doc.get("name", "")
            cont   = doc.get("content", "").strip()
            # Resolver referencias @doc.md con detección de ciclos
            cont   = resolve_doc_references(cont, loading_stack=[name])
            desc   = doc.get("description", "").strip()
            path   = f"{folder}/{name}" if folder else name
            use_l  = f"USO: {desc}\n" if desc else ""
            docs.append(f"### [{path}]\n{use_l}{cont}")
        ctx_text = "\n\n---\n\n".join(docs)
    except Exception:
        ctx_text = ""

    system_prompt = sp_template.replace("{ctx}", ctx_text)

    user_msg = build_user_message(config)

    VALID = {"claude-haiku-4-5-20251001", "claude-sonnet-4-6", "claude-opus-4-6"}
    model = config.get("model", "claude-sonnet-4-6")
    if model not in VALID:
        model = "claude-sonnet-4-6"

    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 10}]
    if not config.get("buscar_web", True):
        tools = []

    full_text      = ""
    search_queries: list[str] = []
    block_type     = ""
    tool_input     = ""

    async with client.messages.stream(
        model=model,
        max_tokens=8192,
        system=system_prompt,
        tools=tools,
        messages=[{"role": "user", "content": user_msg}],
    ) as stream:
        async for event in stream:
            etype = getattr(event, "type", "") or ""
            if etype == "content_block_start":
                block = getattr(event, "content_block", None)
                block_type = getattr(block, "type", "") or ""
                tool_input = ""
            elif etype == "content_block_delta":
                delta = getattr(event, "delta", None)
                dtype = getattr(delta, "type", "") or ""
                if dtype == "text_delta":
                    full_text += getattr(delta, "text", "")
                elif dtype == "input_json_delta":
                    tool_input += getattr(delta, "partial_json", "")
            elif etype == "content_block_stop":
                if block_type == "tool_use" and tool_input:
                    try:
                        ti = json.loads(tool_input)
                        q  = ti.get("query", "")
                        if q:
                            search_queries.append(q)
                    except Exception:
                        pass

    # Extraer JSON
    newsletter_json = extract_json(full_text)
    return newsletter_json, search_queries


# ── Envío de email vía Resend ─────────────────────────────────────────────────
def send_email(to: str, subject: str, html: str) -> str:
    """
    Envía un email con Resend. Retorna el ID del email enviado.
    """
    import resend
    resend.api_key = _resend_key
    resp = resend.Emails.send({
        "from":    _from_email,
        "to":      [t.strip() for t in to.split(",")],
        "subject": subject,
        "html":    html,
    })
    return resp.get("id", "")


# ── Cálculo de next_run ───────────────────────────────────────────────────────
def calc_next_run(cron_expr: str) -> str:
    """Devuelve el próximo datetime en ISO 8601 UTC para la expresión cron dada."""
    now  = datetime.datetime.utcnow()
    it   = croniter(cron_expr, now)
    nxt  = it.get_next(datetime.datetime)
    return nxt.isoformat() + "Z"


# ── Script principal ──────────────────────────────────────────────────────────
async def run_due_schedules():
    if not supabase:
        print("[run_due] Supabase no configurado. Saliendo.")
        return

    now_iso = datetime.datetime.utcnow().isoformat() + "Z"
    print(f"[run_due] Ejecutando a {now_iso}")

    try:
        resp = supabase.table("schedules").select("*").eq("active", True).lte("next_run", now_iso).execute()
    except Exception as e:
        print(f"[run_due] Error consultando schedules: {e}")
        return

    if not resp.data:
        print("[run_due] Sin schedules pendientes.")
        return

    for sched in resp.data:
        sid    = sched["id"]
        name   = sched.get("name", "Schedule sin nombre")
        config = sched.get("config", {})
        email  = sched.get("email_to", "")
        cron   = sched.get("cron", "0 7 * * 1")

        print(f"[run_due] Procesando: {name} ({sid})")

        try:
            newsletter, queries = await generate_once(config)
        except Exception as e:
            print(f"[run_due] Error generando newsletter para {name}: {e}")
            continue

        titulo  = newsletter.get("titulo", name)
        subject = f"Newsletter GovLab — {titulo}"
        html    = render_email_html(newsletter, subject=subject)

        # Enviar email
        email_id = ""
        if email and _resend_key:
            try:
                email_id = send_email(email, subject, html)
                print(f"[run_due] Email enviado a {email} (id={email_id})")
            except Exception as e:
                print(f"[run_due] Error enviando email para {name}: {e}")
        else:
            print(f"[run_due] Sin email destino o RESEND_API_KEY. Solo registrando reporte.")

        # Guardar reporte
        try:
            supabase.table("reports").insert({
                "titulo":         titulo,
                "origen":         "programado",
                "config":         config,
                "newsletter":     newsletter,
                "search_queries": queries,
            }).execute()
        except Exception as e:
            print(f"[run_due] Error guardando reporte para {name}: {e}")

        # Actualizar last_run y next_run
        next_run = calc_next_run(cron)
        try:
            supabase.table("schedules").update({
                "last_run": now_iso,
                "next_run": next_run,
            }).eq("id", sid).execute()
        except Exception as e:
            print(f"[run_due] Error actualizando schedule {sid}: {e}")

    print("[run_due] Listo.")


if __name__ == "__main__":
    asyncio.run(run_due_schedules())
