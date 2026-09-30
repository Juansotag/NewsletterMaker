"""
backend/migrate_supabase_to_postgres.py
Script utilitario para migrar datos existentes desde Supabase hacia la base de datos PostgreSQL de Railway.
Lee las tablas 'documents', 'schedules' y 'reports' de Supabase e inserta los registros en la base de datos SQL activa.

Uso:
  python -m backend.migrate_supabase_to_postgres
"""
import os
import httpx
from dotenv import load_dotenv

load_dotenv(override=True)

from backend.database import init_db, SessionLocal, Document, Schedule, Report

def migrate():
    init_db()

    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    supabase_key = (
        os.environ.get("SUPABASE_SECRET_KEY")
        or os.environ.get("SUPABASE_SERVICE_KEY")
        or os.environ.get("SUPABASE_KEY")
    )

    if not supabase_url or not supabase_key:
        print("[migración] SUPABASE_URL o SUPABASE_SECRET_KEY no configuradas en .env. Saltando migración remota.")
        return

    try:
        from supabase import create_client, ClientOptions
        opts = ClientOptions(httpx_client=httpx.Client(verify=False))
        client = create_client(supabase_url, supabase_key, options=opts)
    except Exception as e:
        print(f"[migración] No fue posible inicializar cliente Supabase: {e}")
        return

    db = SessionLocal()

    # 1. Migrar Documents
    try:
        print("[migración] Consultando documentos en Supabase...")
        res = client.table("documents").select("*").execute()
        rows = res.data or []
        doc_count = 0
        for r in rows:
            existing = db.query(Document).filter(Document.id == r.get("id")).first()
            if not existing:
                doc = Document(
                    id=r.get("id"),
                    folder=r.get("folder") or "",
                    name=r.get("name") or "",
                    content=r.get("content") or "",
                    description=r.get("description") or "",
                    tag_context=r.get("tag_context") or "always",
                    is_system_prompt=bool(r.get("is_system_prompt")),
                    sort_order=r.get("sort_order") or 0,
                )
                db.add(doc)
                doc_count += 1
        db.commit()
        print(f"[migración] {doc_count} documentos migrados de Supabase a SQL.")
    except Exception as e:
        db.rollback()
        print(f"[migración] Error migrando documents: {e}")

    # 2. Migrar Schedules
    try:
        print("[migración] Consultando schedules en Supabase...")
        res = client.table("schedules").select("*").execute()
        rows = res.data or []
        sched_count = 0
        for r in rows:
            existing = db.query(Schedule).filter(Schedule.id == r.get("id")).first()
            if not existing:
                target = r.get("whatsapp_to") or r.get("email_to") or ""
                sched = Schedule(
                    id=r.get("id"),
                    name=r.get("name") or "Schedule",
                    config=r.get("config") or {},
                    email_to=target,
                    cron=r.get("cron") or "0 7 * * 1",
                    next_run=r.get("next_run"),
                    last_run=r.get("last_run"),
                    active=bool(r.get("active", True)),
                )
                db.add(sched)
                sched_count += 1
        db.commit()
        print(f"[migración] {sched_count} schedules migrados de Supabase a SQL.")
    except Exception as e:
        db.rollback()
        print(f"[migración] Error migrando schedules: {e}")

    # 3. Migrar Reports
    try:
        print("[migración] Consultando reportes en Supabase...")
        res = client.table("reports").select("*").execute()
        rows = res.data or []
        rep_count = 0
        for r in rows:
            existing = db.query(Report).filter(Report.id == r.get("id")).first()
            if not existing:
                rep = Report(
                    id=r.get("id"),
                    titulo=r.get("titulo") or "Newsletter sin título",
                    origen=r.get("origen") or "manual",
                    config=r.get("config") or {},
                    newsletter=r.get("newsletter") or {},
                    search_queries=r.get("search_queries") or [],
                )
                db.add(rep)
                rep_count += 1
        db.commit()
        print(f"[migración] {rep_count} reportes migrados de Supabase a SQL.")
    except Exception as e:
        db.rollback()
        print(f"[migración] Error migrando reports: {e}")

    db.close()
    print("[migración] Proceso de migración finalizado.")


if __name__ == "__main__":
    migrate()
