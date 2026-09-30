"""
backend/run_due.py
Script de Cron Job para Railway: genera y envía los newsletters programados cuyo next_run ya venció.
Utiliza base de datos SQL nativa (PostgreSQL en Railway / SQLite en local).

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
from croniter import croniter

from backend.database import init_db, SessionLocal, Document as DBDocument, Schedule as DBSchedule, Report as DBReport
from backend.email_render import render_email_html
from backend.whatsapp_render import render_whatsapp_text
from backend.whatsapp_client import send_whatsapp_text, send_whatsapp_document
from backend.pdf_generator import generate_newsletter_pdf
from backend.main import resolve_doc_references, extract_json, build_user_message, DEFAULT_SYSTEM_PROMPT_TEMPLATE, sanitize_newsletter_dates


# ── Generación con Claude (Anthropic) ──────────────────────────────────────────
async def generate_once(config: dict, api_key: str = "") -> tuple[dict, list[str]]:
    """
    Genera el newsletter completo usando Claude con búsqueda web nativa.
    Retorna (newsletter_json, search_queries).
    """
    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise ValueError("ANTHROPIC_API_KEY no configurada en variables de entorno")

    client = anthropic.AsyncAnthropic(api_key=key)

    # System prompt
    sp_template = DEFAULT_SYSTEM_PROMPT_TEMPLATE
    try:
        with SessionLocal() as db:
            sys_doc = db.query(DBDocument).filter(DBDocument.is_system_prompt == True).first()
            if sys_doc and sys_doc.content:
                sp_template = sys_doc.content
    except Exception:
        sp_template = DEFAULT_SYSTEM_PROMPT_TEMPLATE

    try:
        with SessionLocal() as db:
            doc_rows = db.query(DBDocument).filter(
                DBDocument.is_system_prompt == False
            ).order_by(DBDocument.sort_order.asc()).all()
            docs = []
            for doc in doc_rows:
                tag = (doc.tag_context or "always").strip().lower()
                if tag == "excluded":
                    continue
                folder = doc.folder or ""
                name   = doc.name or ""
                cont   = (doc.content or "").strip()
                cont   = resolve_doc_references(cont, loading_stack=[name])
                desc   = (doc.description or "").strip()
                path   = f"{folder}/{name}" if folder else name
                use_l  = f"USO: {desc}\n" if desc else ""
                docs.append(f"### [{path}]\n{use_l}{cont}")
            ctx_text = "\n\n---\n\n".join(docs)
    except Exception:
        ctx_text = ""

    system_prompt = sp_template.replace("{ctx}", ctx_text or "Universidad de La Sabana — Dirección General de Proyección Social y Co-Creación")
    user_msg = build_user_message(config)

    VALID = {"claude-sonnet-4-6", "claude-haiku-4-5-20251001", "claude-opus-4-6"}
    model = config.get("model", "claude-sonnet-4-6")
    if model not in VALID:
        model = "claude-sonnet-4-6"

    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 10}] if config.get("buscar_web", True) else []

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
                block_type = ""
                tool_input = ""

    newsletter_json = extract_json(full_text)
    hoy_rd = datetime.date.today()
    p_dias = config.get("periodo_dias") or 7 if isinstance(config, dict) else 7
    f_desde_rd = hoy_rd - datetime.timedelta(days=p_dias)
    newsletter_json = sanitize_newsletter_dates(newsletter_json, f_desde_rd, hoy_rd)
    return newsletter_json, search_queries


# ── Cálculo de next_run ───────────────────────────────────────────────────────
def calc_next_run(cron_expr: str) -> str:
    """Devuelve el próximo datetime en ISO 8601 UTC para la expresión cron dada."""
    now  = datetime.datetime.utcnow()
    it   = croniter(cron_expr, now)
    nxt  = it.get_next(datetime.datetime)
    return nxt.isoformat() + "Z"


# ── Script principal ──────────────────────────────────────────────────────────
async def run_due_schedules():
    init_db()
    now_iso = datetime.datetime.utcnow().isoformat() + "Z"
    print(f"[run_due] Ejecutando a {now_iso}")

    try:
        with SessionLocal() as db:
            due_rows = db.query(DBSchedule).filter(
                DBSchedule.active == True,
                DBSchedule.next_run <= now_iso
            ).all()
            due_schedules = [s.to_dict() for s in due_rows]
    except Exception as e:
        print(f"[run_due] Error consultando schedules: {e}")
        return

    if not due_schedules:
        print("[run_due] Sin schedules pendientes.")
        return

    for sched in due_schedules:
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
                    # Enviar PDF adjunto
                    try:
                        pdf_bytes = generate_newsletter_pdf(newsletter)
                        clean_fecha = newsletter.get("fecha") or datetime.date.today().isoformat()
                        pdf_filename = f"Radar_Ejecutivo_{clean_fecha}.pdf"
                        pdf_res = send_whatsapp_document(
                            target,
                            pdf_bytes,
                            filename=pdf_filename,
                            caption=f"{titulo} — Universidad de La Sabana"
                        )
                        if pdf_res.get("success"):
                            print(f"[run_due] PDF adjunto enviado a {target}")
                        else:
                            print(f"[run_due] Aviso enviando PDF: {pdf_res.get('error')}")
                    except Exception as pe:
                        print(f"[run_due] Error generando/enviando PDF adjunto: {pe}")
                else:
                    print(f"[run_due] Error enviando WhatsApp a {target}: {res.get('error')}")
            except Exception as e:
                print(f"[run_due] Excepción enviando WhatsApp para {name}: {e}")
        else:
            print(f"[run_due] Sin destinatario de WhatsApp para {name}. Solo registrando reporte.")

        # Guardar reporte
        try:
            with SessionLocal() as db:
                rep = DBReport(
                    titulo=titulo,
                    origen="programado",
                    config=config,
                    newsletter=newsletter,
                    search_queries=queries,
                )
                db.add(rep)
                db.commit()
        except Exception as e:
            print(f"[run_due] Error guardando reporte para {name}: {e}")

        # Actualizar last_run y next_run
        next_run = calc_next_run(cron)
        try:
            with SessionLocal() as db:
                sched_item = db.query(DBSchedule).filter(DBSchedule.id == sid).first()
                if sched_item:
                    sched_item.last_run = now_iso
                    sched_item.next_run = next_run
                    db.commit()
        except Exception as e:
            print(f"[run_due] Error actualizando schedule {sid}: {e}")

    print("[run_due] Listo.")


if __name__ == "__main__":
    asyncio.run(run_due_schedules())
