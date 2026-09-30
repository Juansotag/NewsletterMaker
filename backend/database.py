"""
backend/database.py
Capa de base de datos SQL (PostgreSQL para producción en Railway / SQLite para desarrollo local).
Reemplaza la dependencia externa de Supabase utilizando SQLAlchemy nativo.
"""
import os
import glob
import uuid
import datetime
from typing import Generator
from sqlalchemy import (
    create_engine,
    Column,
    String,
    Text,
    Boolean,
    Integer,
    JSON,
    DateTime,
    UniqueConstraint
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session

# ── Configuración de Conexión ──────────────────────────────────────────────────
raw_db_url = os.environ.get("DATABASE_URL", "").strip().strip('"').strip("'")

if raw_db_url and not raw_db_url.startswith("$") and not raw_db_url.startswith("{"):
    # Railway a veces expone URLs con 'postgres://' o 'postgresql://' sin driver explícito.
    # En SQLAlchemy 2.0+, 'postgresql://' intenta usar 'psycopg' (v3).
    # Forzamos 'postgresql+psycopg2://' para asegurar compatibilidad con psycopg2.
    if raw_db_url.startswith("postgres://"):
        DB_URL = raw_db_url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif raw_db_url.startswith("postgresql://") and not raw_db_url.startswith("postgresql+"):
        DB_URL = raw_db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
    else:
        DB_URL = raw_db_url
else:
    if raw_db_url:
        print(f"[database] AVISO: DATABASE_URL tiene valor no resuelto '{raw_db_url}'. Usando SQLite de respaldo.")
    # Fallback local a SQLite si no se configuró DATABASE_URL válida
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(ROOT, "newsletter.db")
    DB_URL = f"sqlite:///{db_path}"

connect_args = {}
if DB_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    DB_URL,
    connect_args=connect_args,
    pool_pre_ping=True
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ── Modelos de Datos ──────────────────────────────────────────────────────────

class Document(Base):
    """Documentos institucionales y directrices de contexto."""
    __tablename__ = "documents"

    id = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    folder = Column(String(255), default="", nullable=False)
    name = Column(String(255), nullable=False)
    content = Column(Text, default="", nullable=False)
    description = Column(Text, default="", nullable=False)
    tag_context = Column(String(50), default="always", nullable=False)
    is_system_prompt = Column(Boolean, default=False, nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("folder", "name", name="uq_doc_folder_name"),
    )

    def to_dict(self, include_content: bool = True) -> dict:
        d = {
            "id": self.id,
            "folder": self.folder or "",
            "name": self.name,
            "description": self.description or "",
            "tag_context": self.tag_context or "always",
            "is_system_prompt": bool(self.is_system_prompt),
            "sort_order": self.sort_order if self.sort_order is not None else 0,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
        if include_content:
            d["content"] = self.content or ""
        return d


class Schedule(Base):
    """Automatización y programación periódica de boletines."""
    __tablename__ = "schedules"

    id = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(255), nullable=False)
    config = Column(JSON, default=dict)
    email_to = Column(String(255), default="")  # Almacena también whatsapp_to
    cron = Column(String(100), default="0 7 * * 1")
    next_run = Column(String(100), nullable=True)
    last_run = Column(String(100), nullable=True)
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=datetime.datetime.utcnow)

    def to_dict(self) -> dict:
        target = self.email_to or ""
        return {
            "id": self.id,
            "name": self.name,
            "config": self.config or {},
            "email_to": target,
            "whatsapp_to": target,
            "cron": self.cron or "0 7 * * 1",
            "next_run": self.next_run,
            "last_run": self.last_run,
            "active": bool(self.active),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Report(Base):
    """Historial de ediciones generadas (manuales o programadas)."""
    __tablename__ = "reports"

    id = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    titulo = Column(String(255), default="Newsletter sin título")
    origen = Column(String(50), default="manual")
    config = Column(JSON, default=dict)
    newsletter = Column(JSON, default=dict)
    search_queries = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), default=datetime.datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "titulo": self.titulo or "Newsletter sin título",
            "origen": self.origen or "manual",
            "config": self.config or {},
            "newsletter": self.newsletter or {},
            "search_queries": self.search_queries or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ── Sesión y Migración Automática ─────────────────────────────────────────────

def get_db_session() -> Generator[Session, None, None]:
    """Generador de sesión SQLAlchemy para endpoints o tareas."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Crea automáticamente todas las tablas si no existen."""
    try:
        Base.metadata.create_all(bind=engine)
        seed_default_docs_if_empty()
    except Exception as e:
        print(f"[init_db] Aviso al inicializar base de datos: {e}")


def seed_default_docs_if_empty():
    """Si la tabla documents está vacía, la inicializa con los archivos de Contexto/."""
    db = SessionLocal()
    try:
        count = db.query(Document).count()
        if count > 0:
            return  # Ya hay datos

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        contexto_dir = os.path.join(root, "Contexto")
        if not os.path.exists(contexto_dir):
            return

        files = sorted(glob.glob(os.path.join(contexto_dir, "*.md")))
        for filepath in files:
            filename = os.path.basename(filepath)
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            is_system_prompt = (filename == "00_sistema_instrucciones.md")
            sort_order = 0
            prefix = filename.split("_")[0]
            if prefix.isdigit():
                sort_order = int(prefix)

            doc = Document(
                name=filename,
                folder="",
                content=content,
                description="",
                tag_context="always",
                is_system_prompt=is_system_prompt,
                sort_order=sort_order
            )
            db.add(doc)

        db.commit()
        print(f"[init_db] Inicializados {len(files)} documentos de contexto exitosamente.")
    except Exception as e:
        print(f"[init_db] Aviso al sembrar documentos: {e}")
        db.rollback()
    finally:
        db.close()
