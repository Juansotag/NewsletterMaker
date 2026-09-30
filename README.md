# Newsletter Ejecutivo — GovLab · Universidad de La Sabana

Plataforma integral para la investigación, generación, diseño y despacho automatizado de boletines ejecutivos de alto impacto para directivos de la **Universidad de La Sabana** (Dirección General de Proyección Social y Co-Creación).

La herramienta combina inteligencia artificial con búsqueda web en vivo, rigor temporal estricto, despacho multicanal directo a **WhatsApp** (texto enriquecido y documento PDF adjunto), programación periódica automatizada y almacenamiento centralizado en **PostgreSQL (Railway)** o SQLite en desarrollo local.

---

## Características Principales

- **Investigación y Curaduría con IA en Tiempo Real**:
  - Motor impulsado por modelos avanzados de Anthropic (Claude Sonnet 4.6) con herramienta nativa de búsqueda web (`web_search`).
  - **Rigor temporal estricto**: Cobertura focalizada en la ventana temporal elegida (últimos días / semana en curso), con filtros heurísticos de sanitización para descartar artículos obsoletos de inicio de año o meses previos.
  - Streaming en tiempo real (SSE) del progreso de búsqueda y redacción del boletín.

- **Despacho Multicanal a WhatsApp**:
  - Envío automático de resúmenes ejecutivos en texto formateado directamente a chats individuales (normalización automática de prefijo internacional `+57`) o grupos (`@g.us`).
  - Generación y envío simultáneo del informe ejecutivo como **documento PDF adjunto**.
  - Soporte modular para proveedores de mensajería: **Evolution API** (recomendado para producción / Railway, basado en Baileys, ligero y sin Chromium) y **Open-Wa**.

- **Generador de PDF Ejecutivo de Alta Calidad**:
  - Motor de renderizado server-side basado en ReportLab ([pdf_generator.py](file:///c:/Users/juans/Downloads/NewsletterMaker/backend/pdf_generator.py)).
  - Diseño editorial institucional: paleta azul UniSabana, tipografía corporativa, métricas destacadas, titulares analíticos y paginación inteligente ("Página X de Y").

- **Programación y Automatización (Schedules & Cron)**:
  - Configuración de envíos periódicos con presets directos (Lunes 7:00 am, Viernes 7:00 am, L-M-V, 1er día del mes) o expresiones cron personalizadas.
  - Ejecución asíncrona en segundo plano desde el dashboard web con monitor de progreso en vivo.
  - Script runner independiente ([backend/run_due.py](file:///c:/Users/juans/Downloads/NewsletterMaker/backend/run_due.py)) listo para programarse como Cron Job en plataformas como Railway.

- **Base de Datos SQL Nativa (PostgreSQL en Railway / SQLite en Local)**:
  - Capa de datos con **SQLAlchemy** ([backend/database.py](file:///c:/Users/juans/Downloads/NewsletterMaker/backend/database.py)) que autoinicializa las tablas (`documents`, `schedules`, `reports`) al arrancar.
  - Si no se especifica `DATABASE_URL` (desarrollo local), utiliza automáticamente SQLite local (`newsletter.db`).
  - En producción, se conecta de forma directa y privada a la base de datos PostgreSQL de Railway sin depender de APIs de terceros.

- **Editor de Contexto Institucional Inteligente**:
  - Gestión de documentos estratégicos en la base de datos (`documents`) con carpetas y orden temático.
  - Resolución automática y recursiva de referencias interdocumentales (`@documento.md`) con protección contra dependencias circulares.
  - Asistente de IA incorporado para refinar, traducir o expandir lineamientos estratégicos protegiendo las especificaciones técnicas del sistema.

- **Historial Centralizado de Reportes**:
  - Registro auditable de cada edición generada (manual o programada) con almacenamiento en la tabla `reports`.
  - Consulta y descarga directa de los PDFs generados en cualquier momento.

- **Interfaz Ejecutiva & Guía Rápida**:
  - Panel unificado de trabajo ([index.html](file:///c:/Users/juans/Downloads/NewsletterMaker/index.html)) con diseño limpio basado en los lineamientos visuales del GovLab y la Universidad de La Sabana.
  - Guía interactiva paso a paso (tour integrado) para nuevos usuarios.
  - Modo demo disponible para previsualizar la experiencia sin necesidad de backend activo.

---

## Estructura del Proyecto

```text
NewsletterMaker/
├── Contexto/                     # Documentos base institucionales en Markdown
│   ├── 00_sistema_instrucciones.md
│   ├── 01_universidad-la-sabana.md
│   └── ...
├── assets/                       # Recursos estáticos del frontend
│   ├── app.js                    # Lógica SPA, estado, llamadas a API y tour interactivo
│   ├── style.css                 # Sistema de diseño institucional y temas
│   ├── Govlab.png                # Logo oficial del GovLab
│   └── Universidad_de_la_Sabana.png # Logo oficial UniSabana
├── backend/                      # Backend FastAPI y lógica de negocio
│   ├── database.py               # Capa SQL (SQLAlchemy): modelos Document, Schedule, Report
│   ├── main.py                   # Rutas REST/SSE, orquestación de IA y servicios
│   ├── whatsapp_client.py        # Cliente modular para Evolution API y Open-Wa
│   ├── whatsapp_render.py        # Conversor del esquema JSON a formato WhatsApp
│   ├── pdf_generator.py          # Generador de PDF institucional con ReportLab
│   ├── email_render.py           # Renderizador HTML para respaldo por correo
│   ├── run_due.py                # Runner de ejecución periódica (Railway Cron Job)
│   ├── seed_docs.py              # Script para inicializar contexto en SQL desde Contexto/
│   └── migrate_supabase_to_postgres.py # Utilidad para transferir datos antiguos desde Supabase
├── index.html                    # Frontend unificado (Single Page Application)
├── run.py                        # Script de inicio rápido local con Uvicorn
├── requirements.txt              # Dependencias de Python
├── Procfile                      # Comando de despliegue para Railway
├── .env.example                  # Plantilla de variables de entorno
└── README.md                     # Documentación del proyecto
```

---

## Variables de Entorno

Copia el archivo de plantilla `.env.example` como `.env` y completa los valores correspondientes:

```bash
cp .env.example .env
```

| Variable | Descripción | Obligatoria |
| :--- | :--- | :--- |
| `DATABASE_URL` | URL de conexión PostgreSQL (en Railway se genera automáticamente al añadir el plugin de PostgreSQL; en local usa SQLite si se deja vacía). | **Sí (en Prod)** |
| `ANTHROPIC_API_KEY` | Clave API de Anthropic para la generación con Claude Sonnet 4.6 y Haiku. | **Sí** |
| `EVOLUTION_API_URL` | URL de la instancia de Evolution API (ej: `http://localhost:8080` o URL en la nube). | Recomendada |
| `EVOLUTION_API_KEY` | Clave global o de autenticación configurada en Evolution API. | Recomendada |
| `EVOLUTION_INSTANCE` | Nombre de la instancia activa de WhatsApp (por defecto: `govlab`). | Recomendada |
| `OPENWA_API_URL` | URL de la API de Open-Wa (alternativa si no se usa Evolution API). | Opcional |
| `OPENWA_API_KEY` | Clave de acceso para la API de Open-Wa. | Opcional |
| `RESEND_API_KEY` | Clave de Resend para respaldo o envío por correo electrónico. | Opcional |
| `RESEND_FROM_EMAIL` | Dirección de remitente verificada para correos. | Opcional |

---

## Puesta en Marcha en Local

### 1. Requisitos Previos
- Python 3.10 o superior instalado.
- Clave API de Anthropic (`ANTHROPIC_API_KEY`).

### 2. Instalación de dependencias
```bash
pip install -r requirements.txt
```

### 3. Configurar entorno
Configura tu clave en `.env` (si dejas `DATABASE_URL` vacía, se creará un archivo SQLite local `newsletter.db` de forma automática).

### 4. Iniciar la aplicación
```bash
python run.py
```
O directamente con Uvicorn:
```bash
uvicorn backend.main:app --reload --port 8000
```
La aplicación creará automáticamente las tablas SQL y cargará los documentos iniciales de `Contexto/` al arrancar. Abre en tu navegador: [http://localhost:8000](http://localhost:8000).

---

## Despliegue en Railway (Paso a Paso)

Sigue estos sencillos pasos para tener todo el ecosistema (Backend + Base de Datos PostgreSQL + Cron Job) corriendo en Railway:

### Paso 1: Agregar el Plugin de PostgreSQL
1. En tu proyecto de [Railway](https://railway.app), haz clic en **+ New** (o botón derecho en el canvas).
2. Selecciona **Database** → **Add PostgreSQL**.
3. Railway creará el servicio de PostgreSQL en segundos y expondrá automáticamente la variable `DATABASE_URL` para conectarse.

### Paso 2: Vincular la Base de Datos a tu Servicio Web
1. Haz clic en tu servicio del backend (el servicio web desplegado desde GitHub).
2. Ve a la pestaña **Variables**.
3. Añade la variable `DATABASE_URL` referenciando el servicio de PostgreSQL recién creado:
   - Haz clic en **Add Reference** o escribe `${{Postgres.DATABASE_URL}}` (o copia la URL de conexión que Railway te muestra en el servicio PostgreSQL).
4. Asegúrate de configurar también en las variables de Railway:
   - `ANTHROPIC_API_KEY`
   - Las variables de WhatsApp (`EVOLUTION_API_URL`, `EVOLUTION_API_KEY`, `EVOLUTION_INSTANCE`).

### Paso 3: Despliegue Automático
1. Haz push de este repositorio a GitHub.
2. Railway compilará con `pip install -r requirements.txt` y ejecutará el comando del `Procfile`:
   ```text
   web: uvicorn backend.main:app --host 0.0.0.0 --port $PORT
   ```
3. Al iniciar, el backend ejecutará `init_db()`, el cual:
   - Creará automáticamente las tablas `documents`, `schedules` y `reports`.
   - Sembrará automáticamente los 11 documentos de contexto institucional de `Contexto/*.md`.

### Paso 4: (Opcional) Migrar datos previos desde Supabase
Si tenías reportes o programaciones creadas en Supabase que deseas trasladar a PostgreSQL de Railway:
1. En tu entorno local (o terminal de Railway), asegúrate de tener `SUPABASE_URL`, `SUPABASE_SECRET_KEY` y `DATABASE_URL` configurados.
2. Ejecuta:
   ```bash
   python -m backend.migrate_supabase_to_postgres
   ```

### Paso 5: Configurar el Cron Job para Envíos Automáticos
1. En el mismo proyecto de Railway, haz clic en **+ New** → **GitHub Repo** (selecciona el mismo repositorio).
2. En la configuración de ese nuevo servicio, cambia el nombre a **Newsletter Cron Runner**.
3. En la sección **Settings** → **Deploy**:
   - Cambia a **Cron Job** (o activa la programación).
   - **Schedule**: `*/15 * * * *` (se ejecuta cada 15 minutos).
   - **Custom Start Command**: `python -m backend.run_due`
4. En la pestaña **Variables**, comparte las mismas variables del servicio web (`DATABASE_URL`, `ANTHROPIC_API_KEY`, credenciales de WhatsApp).

---

## Flujo de Trabajo y Endpoints Principales

| Método | Endpoint | Descripción |
| :--- | :--- | :--- |
| `POST` | `/api/generate/stream` | Genera un newsletter en streaming SSE usando Claude y búsqueda web en vivo. Guarda el resultado en la tabla `reports`. |
| `GET` | `/api/schedules` | Lista las programaciones automáticas registradas en PostgreSQL. |
| `POST` | `/api/schedules` | Crea una nueva programación con destinatario de WhatsApp y frecuencia cron. |
| `POST` | `/api/schedules/{id}/run` | Inicia la generación y despacho manual e inmediato en segundo plano. |
| `GET` | `/api/schedules/{id}/status` | Monitorea el estado en vivo de una tarea en segundo plano. |
| `POST` | `/api/whatsapp/send` | Envía directamente un newsletter existente (texto enriquecido y PDF adjunto). |
| `GET` | `/api/whatsapp/status` | Verifica la conectividad y estado de la sesión de WhatsApp. |
| `GET` | `/api/reports` | Lista el historial de newsletters generados desde la tabla `reports`. |
| `GET` | `/api/reports/{id}/pdf` | Genera y descarga el PDF institucional de un reporte específico. |
| `GET` | `/api/docs` | Obtiene los documentos institucionales de contexto desde la tabla `documents`. |
| `POST` | `/api/docs/assist` | Asistente de IA para optimizar o revisar documentos de contexto. |

---

## Identidad y Créditos

Desarrollado para el **Laboratorio de Gobierno (GovLab)** y la **Dirección General de Proyección Social y Co-Creación** de la **Universidad de La Sabana**.
