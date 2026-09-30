"""
backend/seed_docs.py
Inicializa o actualiza los documentos de contexto institucional en la base de datos SQL
a partir de los archivos Markdown ubicados en la carpeta Contexto/.
"""
import os
import glob
from dotenv import load_dotenv

load_dotenv(override=True)

from backend.database import init_db, SessionLocal, Document

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTEXTO_DIR = os.path.join(ROOT, "Contexto")


def seed():
    init_db()
    search_path = os.path.join(CONTEXTO_DIR, "*.md")
    files = sorted(glob.glob(search_path))

    if not files:
        print(f"[seed_docs] No se encontraron archivos markdown en {CONTEXTO_DIR}")
        return

    print(f"[seed_docs] Se encontraron {len(files)} archivos markdown en {CONTEXTO_DIR}")

    db = SessionLocal()
    inserted = 0
    updated = 0
    try:
        for filepath in files:
            filename = os.path.basename(filepath)

            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            is_system_prompt = (filename == "00_sistema_instrucciones.md")
            sort_order = 0
            prefix = filename.split("_")[0]
            if prefix.isdigit():
                sort_order = int(prefix)

            # Buscar si ya existe por folder y name
            doc = db.query(Document).filter(
                Document.folder == "",
                Document.name == filename
            ).first()

            if doc:
                doc.content = content
                doc.is_system_prompt = is_system_prompt
                doc.sort_order = sort_order
                updated += 1
            else:
                doc = Document(
                    folder="",
                    name=filename,
                    content=content,
                    description="",
                    tag_context="always",
                    is_system_prompt=is_system_prompt,
                    sort_order=sort_order,
                )
                db.add(doc)
                inserted += 1

        db.commit()
        print(f"[seed_docs] Operación completada exitosamente: {inserted} insertados, {updated} actualizados.")
    except Exception as e:
        db.rollback()
        print(f"[seed_docs] Error durante el sembrado: {e}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
