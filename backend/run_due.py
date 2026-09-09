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
from backend.whatsapp_render import render_whatsapp_text
from backend.whatsapp_client import send_whatsapp_text
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


# ── Generación con OpenAI (GPT-4o) ─────────────────────────────────────────────
async def generate_once(config: dict, api_key: str = "") -> tuple[dict, list[str]]:
    """
    Genera el newsletter completo usando OpenAI GPT-4o con búsqueda web.
    Retorna (newsletter_json, search_queries).
    """
    import openai
    from backend.web_search import perform_web_search, format_search_results_for_llm
    from backend.main import WEB_SEARCH_TOOL

    key = api_key or os.environ.get("OPENAI_API_KEY", "")
    if not key:
        raise ValueError("OPENAI_API_KEY no configurada")

    client = openai.AsyncOpenAI(api_key=key)

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

    model = config.get("model", "gpt-4o")
    if "claude" in model.lower():
        model = "gpt-4o"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg}
    ]

    tools = [WEB_SEARCH_TOOL] if config.get("buscar_web", True) else None
    search_queries: list[str] = []

    # Ronda de búsqueda web si está activada
    max_search_rounds = 3
    round_idx = 0

    while config.get("buscar_web", True) and round_idx < max_search_rounds:
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
            break

        messages.append(msg)

        for tc in tool_calls:
            if tc.function.name == "web_search":
                try:
                    args = json.loads(tc.function.arguments)
                    q = args.get("query", "")
                except Exception:
                    q = tc.function.arguments or ""

                if q:
                    search_queries.append(q)
                    raw_results = perform_web_search(q, max_results=5)
                    content_str = format_search_results_for_llm(raw_results)
                else:
                    content_str = "No se proporcionó término de búsqueda."

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": content_str
                })

    # Generación final estructurada
    final_resp = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.7,
    )
    full_text = final_resp.choices[0].message.content or "{}"
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
        target = sched.get("whatsapp_to") or sched.get("email_to", "")
        cron   = sched.get("cron", "0 7 * * 1")

        print(f"[run_due] Procesando: {name} ({sid})")

        try:
            newsletter, queries = await generate_once(config)
        except Exception as e:
            print(f"[run_due] Error generando newsletter para {name}: {e}")
            continue

        titulo = newsletter.get("titulo", name)
        whatsapp_msg = render_whatsapp_text(newsletter)

        # Enviar WhatsApp
        whatsapp_id = ""
        if target:
            try:
                res = send_whatsapp_text(target, whatsapp_msg)
                if res.get("success"):
                    whatsapp_id = res.get("id", "")
                    print(f"[run_due] WhatsApp enviado a {target} (id={whatsapp_id})")
                else:
                    print(f"[run_due] Error enviando WhatsApp a {target}: {res.get('error')}")
            except Exception as e:
                print(f"[run_due] Excepción enviando WhatsApp para {name}: {e}")
        else:
            print(f"[run_due] Sin destinatario de WhatsApp para {name}. Solo registrando reporte.")

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
