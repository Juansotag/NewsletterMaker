# Newsletter Ejecutivo — GovLab · Universidad de La Sabana

Plataforma integral para la investigación, generación, diseño y despacho automatizado de boletines ejecutivos de alto impacto para directivos de la **Universidad de La Sabana** (Dirección General de Proyección Social y Co-Creación).

La herramienta combina inteligencia artificial de última generación con búsqueda web en vivo, rigor temporal estricto, despacho multicanal directo a **WhatsApp** (texto enriquecido y documento PDF adjunto), programación periódica automatizada y gestión dinámica del contexto institucional en la nube.

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
  - Motor de renderizado server-side basado en ReportLab (`backend/pdf_generator.py`).
  - Diseño editorial institucional: paleta azul UniSabana, tipografía corporativa, métricas destacadas, titulares analíticos y paginación inteligente ("Página X de Y").

- **Programación y Automatización (Schedules & Cron)**:
  - Configuración de envíos periódicos con presets directos (Lunes 7:00 am, Viernes 7:00 am, L-M-V, 1er día del mes) o expresiones cron personalizadas.
  - Ejecución asíncrona en segundo plano desde el dashboard web con monitor de progreso en vivo.
  - Script independiente (`python -m backend.run_due`) listo para programarse como Cron Job en plataformas como Railway.

- **Editor de Contexto Institucional Inteligente**:
  - Base de conocimiento persistente en **Supabase** (`documents`) estructurada por carpetas y orden temático.
  - Resolución automática y recursiva de referencias interdocumentales (`@documento.md`) con protección contra dependencias circulares.
  - Asistente de IA incorporado para refinar, traducir o expandir lineamientos estratégicos protegiendo las especificaciones técnicas del sistema.

- **Historial Centralizado de Reportes**:
  - Registro auditable de cada edición generada (manual o programada) con almacenamiento en Supabase (`reports`).
  - Consulta y descarga directa de los PDFs generados en cualquier momento.

- **Interfaz Ejecutiva & Guía Rápida**:
  - Panel unificado de trabajo (`index.html`) con diseño limpio basado en los lineamientos visuales del GovLab y la Universidad de La Sabana.
  - Guía interactiva paso a paso (tour integrado) para nuevos usuarios.
  - Modo demo disponible para previsualizar la experiencia sin necesidad de backend activo.

---

## Estructura del Proyecto

```text
NewsletterMaker/
├── assets/                       # Recursos estáticos del frontend
│   ├── app.js                    # Lógica SPA, estado, llamadas a API y tour interactivo
│   ├── style.css                 # Sistema de diseño, temas y diseño responsivo
│   ├── Govlab.png                # Logo oficial del GovLab
│   ├── Universidad_de_la_Sabana.png  # Logo oficial UniSabana
│   ├── marked.min.js             # Renderizador de Markdown
│   └── html2pdf.bundle.min.js    # Utilidad de exportación PDF cliente
├── backend/                      # Backend FastAPI y lógica de negocio
│   ├── main.py                   # Rutas REST/SSE, orquestación de IA y servicios
│   ├── whatsapp_client.py        # Cliente modular para Evolution API y Open-Wa
│   ├── whatsapp_render.py        # Conversor del esquema JSON a formato WhatsApp
│   ├── pdf_generator.py          # Generador de PDF institucional con ReportLab
│   ├── email_render.py           # Renderizador HTML para respaldo por correo
│   ├── run_due.py                # Runner de ejecución periódica (Railway Cron Job)
│   └── seed_docs.py              # Script para inicializar contexto en Supabase
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
| `ANTHROPIC_API_KEY` | Clave API de Anthropic para la generación con Claude Sonnet 4.6 y Haiku. | **Sí** |
| `SUPABASE_URL` | URL de tu instancia de Supabase (`https://xxxx.supabase.co`). | **Sí** |
| `SUPABASE_SECRET_KEY` | Clave `service_role` o secret key de Supabase (permite lectura/escritura de contexto, reportes y programaciones). | **Sí** |
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
- Cuenta o instancia configurada de Supabase y clave API de Anthropic.
- (Opcional para envíos reales de WhatsApp) Instancia de Evolution API vinculada mediante código QR.

### 2. Instalación de dependencias
```bash
pip install -r requirements.txt
```

### 3. Configurar entorno
Configura las credenciales en `.env` a partir de `.env.example`.

### 4. Inicializar documentos de contexto (opcional)
Si es una base de datos nueva en Supabase y deseas cargar los documentos iniciales de contexto:
```bash
python -m backend.seed_docs
```

### 5. Iniciar la aplicación
Puedes iniciarla con el script directo:
```bash
python run.py
```
O ejecutando Uvicorn directamente:
```bash
uvicorn backend.main:app --reload --port 8000
```

Abre en tu navegador: [http://localhost:8000](http://localhost:8000)

> **Modo Demo**: Puedes abrir directamente el archivo `index.html` en el navegador (doble clic) para explorar la interfaz y ver un newsletter pre-cargado de ejemplo sin necesidad de levantar el servidor backend.

---

## Despliegue en Railway

El proyecto está preparado para su despliegue en [Railway](https://railway.app):

1. **Crear Servicio Web Principal**:
   - Conecta el repositorio de GitHub a un nuevo proyecto en Railway.
   - En la sección **Variables**, agrega todas las variables descritas en la sección anterior (`ANTHROPIC_API_KEY`, `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, credenciales de WhatsApp, etc.).
   - Railway detectará Python y usará el archivo `Procfile` automáticamente:
     ```text
     web: uvicorn backend.main:app --host 0.0.0.0 --port $PORT
     ```

2. **Configurar Cron Job para Envíos Automáticos**:
   - En el mismo proyecto de Railway, añade un servicio de tipo **Cron Job** apuntando al mismo repositorio.
   - **Comando de ejecución**:
     ```bash
     python -m backend.run_due
     ```
   - **Programación (Schedule)**: Cada 15 minutos para evaluar periódicamente los boletines que hayan cumplido su hora de envío:
     ```cron
     */15 * * * *
     ```
   - Asegúrate de compartir las mismas variables de entorno en el servicio del Cron Job.

---

## Flujo de Trabajo y Endpoints Principales

| Método | Endpoint | Descripción |
| :--- | :--- | :--- |
| `POST` | `/api/generate/stream` | Genera un newsletter en streaming SSE usando Claude y búsqueda web en vivo. |
| `GET` | `/api/schedules` | Lista las programaciones automáticas registradas. |
| `POST` | `/api/schedules` | Crea una nueva programación con destinatario de WhatsApp y frecuencia cron. |
| `POST` | `/api/schedules/{id}/run` | Inicia la generación y despacho manual e inmediato en segundo plano. |
| `GET` | `/api/schedules/{id}/status` | Monitorea el estado en vivo de una tarea en segundo plano. |
| `POST` | `/api/whatsapp/send` | Envía directamente un newsletter existente (texto enriquecido y PDF adjunto). |
| `GET` | `/api/whatsapp/status` | Verifica la conectividad y estado de la sesión de WhatsApp. |
| `GET` | `/api/reports` | Lista el historial de newsletters generados. |
| `GET` | `/api/reports/{id}/pdf` | Genera y descarga el PDF institucional de un reporte específico. |
| `GET` | `/api/docs` | Obtiene los documentos institucionales de contexto desde Supabase. |
| `POST` | `/api/docs/assist` | Asistente de IA para optimizar o revisar documentos de contexto. |

---

## Identidad y Créditos

Desarrollado para el **Laboratorio de Gobierno (GovLab)** y la **Dirección General de Proyección Social y Co-Creación** de la **Universidad de La Sabana**.
