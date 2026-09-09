"""
backend/whatsapp_client.py
Cliente HTTP modular para WhatsApp.
Soporta:
1. Evolution API (Recomendado para Railway / Docker, basado en Baileys, ligero y sin navegador Chromium).
2. Open-Wa (@open-wa/wa-automate REST).
"""
from __future__ import annotations
import os
import re
import httpx
from typing import Optional


def normalize_whatsapp_number(to: str, for_evolution: bool = False) -> str:
    """
    Normaliza el número o identificador de WhatsApp.
    - Para Evolution API: solo dígitos internacionales (ej: '573001234567') o ID de grupo.
    - Para Open-Wa: con sufijo '@c.us' o '@g.us'.
    """
    cleaned = to.strip()
    if not cleaned:
        return ""

    # Si es grupo, conservar el formato del grupo
    if "@g.us" in cleaned:
        return cleaned

    # Quitar cualquier carácter no numérico
    digits = re.sub(r'\D', '', cleaned)
    if not digits:
        return cleaned

    # Si es número móvil colombiano de 10 dígitos (ej: 3101234567), agregar prefijo país 57
    if len(digits) == 10 and digits.startswith('3'):
        digits = f"57{digits}"

    if for_evolution:
        return digits
    return f"{digits}@c.us"


def get_whatsapp_config() -> dict:
    """Obtiene la configuración del proveedor de WhatsApp desde el entorno."""
    # Detectar proveedor o URLs
    provider = os.environ.get("WHATSAPP_PROVIDER", "").strip().lower()
    
    evo_url = os.environ.get("EVOLUTION_API_URL", "")
    openwa_url = os.environ.get("OPENWA_API_URL", "")
    generic_url = os.environ.get("WHATSAPP_API_URL", "")

    url = evo_url or generic_url or openwa_url or "http://localhost:8080"
    url = url.rstrip("/")

    key = (
        os.environ.get("EVOLUTION_API_KEY")
        or os.environ.get("WHATSAPP_API_KEY")
        or os.environ.get("OPENWA_API_KEY", "")
    ).strip()

    instance = os.environ.get("EVOLUTION_INSTANCE", "govlab").strip()

    # Si no se definió proveedor explícito, inferir por variables
    if not provider:
        if evo_url or os.environ.get("EVOLUTION_API_KEY"):
            provider = "evolution"
        else:
            provider = "openwa"

    return {
        "provider": provider,
        "url": url,
        "key": key,
        "instance": instance,
    }


def check_whatsapp_status() -> dict:
    """Verifica si el servidor de WhatsApp está disponible y autenticado."""
    cfg = get_whatsapp_config()
    provider = cfg["provider"]
    url = cfg["url"]
    key = cfg["key"]
    instance = cfg["instance"]

    headers = {"Content-Type": "application/json"}
    if key:
        headers["apikey"] = key
        headers["Authorization"] = f"Bearer {key}"
        headers["api_key"] = key

    try:
        with httpx.Client(timeout=3.0, verify=False) as client:
            # ── 1. Evolution API ───────────────────────────────────────────
            if provider == "evolution":
                try:
                    r = client.get(f"{url}/instance/connectionState/{instance}", headers=headers)
                    if r.status_code == 200:
                        data = r.json()
                        state = data.get("instance", {}).get("state") or data.get("state", "")
                        is_open = (state == "open")
                        return {
                            "online": True,
                            "connected": is_open,
                            "provider": "Evolution API",
                            "url": url,
                            "message": "Evolution API conectada a WhatsApp (sesion activa)" if is_open else f"Evolution API online, pero sesión en estado '{state}' (requiere escanear QR)"
                        }
                    elif r.status_code == 404:
                        return {
                            "online": True,
                            "connected": False,
                            "provider": "Evolution API",
                            "url": url,
                            "message": f"Instancia '{instance}' no encontrada en Evolution API. Créala desde el dashboard de Evolution."
                        }
                except (httpx.ConnectError, ConnectionRefusedError):
                    raise
                except Exception:
                    pass

            # ── 2. Open-Wa ─────────────────────────────────────────────────
            try:
                r = client.get(f"{url}/isConnected", headers=headers)
                if r.status_code == 200:
                    data = r.json()
                    is_conn = data.get("response", data) is True or data is True
                    return {
                        "online": True,
                        "connected": is_conn,
                        "provider": "Open-Wa",
                        "url": url,
                        "message": "Open-Wa conectado y activo" if is_conn else "Open-Wa en línea, requiere escanear código QR"
                    }
            except (httpx.ConnectError, ConnectionRefusedError):
                raise
            except Exception:
                pass

            # Intento genérico de health check
            r = client.get(f"{url}/", headers=headers)
            return {
                "online": True,
                "connected": False,
                "provider": provider,
                "url": url,
                "message": f"Servidor de WhatsApp en línea (HTTP {r.status_code})"
            }

    except (httpx.ConnectError, ConnectionRefusedError):
        return {
            "online": False,
            "connected": False,
            "provider": provider,
            "url": url,
            "message": f"Servidor de WhatsApp no disponible en {url}"
        }
    except Exception as e:
        return {
            "online": False,
            "connected": False,
            "provider": provider,
            "url": url,
            "message": f"Error verificando WhatsApp: {str(e)}"
        }


def send_whatsapp_text(to: str, text: str) -> dict:
    """
    Envía un mensaje de texto a través del servidor configurado (Evolution API u Open-Wa).
    """
    cfg = get_whatsapp_config()
    provider = cfg["provider"]
    url = cfg["url"]
    key = cfg["key"]
    instance = cfg["instance"]

    headers = {"Content-Type": "application/json"}
    if key:
        headers["apikey"] = key
        headers["Authorization"] = f"Bearer {key}"
        headers["api_key"] = key

    try:
        with httpx.Client(timeout=30.0, verify=False) as client:

            # ── Enviar vía Evolution API ───────────────────────────────────────
            if provider == "evolution":
                number = normalize_whatsapp_number(to, for_evolution=True)
                if not number:
                    raise ValueError("Número de WhatsApp destinatario vacío o inválido")

                payload = {
                    "number": number,
                    "text": text,
                    "options": {
                        "delay": 1200,
                        "presence": "composing",
                        "linkPreview": True
                    }
                }
                endpoint = f"{url}/message/sendText/{instance}"
                resp = client.post(endpoint, json=payload, headers=headers)

                if resp.status_code in (200, 201):
                    data = resp.json()
                    msg_id = data.get("key", {}).get("id") or str(data.get("id", ""))
                    return {"success": True, "id": msg_id, "chat_id": number, "error": ""}
                else:
                    return {
                        "success": False,
                        "id": "",
                        "chat_id": number,
                        "error": f"Evolution API HTTP {resp.status_code}: {resp.text}"
                    }

            # ── Enviar vía Open-Wa ─────────────────────────────────────────────
            else:
                chat_id = normalize_whatsapp_number(to, for_evolution=False)
                if not chat_id:
                    raise ValueError("Número de WhatsApp destinatario vacío o inválido")

                payload = {
                    "chatId": chat_id,
                    "to": chat_id,
                    "content": text,
                    "text": text,
                }
                resp = client.post(f"{url}/sendText", json=payload, headers=headers)

                if resp.status_code in (200, 201):
                    data = resp.json()
                    msg_id = str(data.get("response", data.get("id", ""))) if isinstance(data, dict) else str(data)
                    return {"success": True, "id": msg_id, "chat_id": chat_id, "error": ""}
                else:
                    return {
                        "success": False,
                        "id": "",
                        "chat_id": chat_id,
                        "error": f"Open-Wa HTTP {resp.status_code}: {resp.text}"
                    }

    except (httpx.ConnectError, ConnectionRefusedError):
        return {
            "success": False,
            "id": "",
            "chat_id": to,
            "error": f"No fue posible conectar con el servidor de WhatsApp en '{url}'. Asegúrate de que el servicio esté corriendo en Railway o en local."
        }
    except Exception as e:
        return {"success": False, "id": "", "chat_id": to, "error": str(e)}


def send_whatsapp_document(to: str, pdf_bytes: bytes, filename: str = "Boletin_Ejecutivo_Unisabana.pdf", caption: str = "") -> dict:
    """
    Envía un documento PDF a través del servidor configurado de WhatsApp (Evolution API u Open-Wa).
    """
    import base64

    cfg = get_whatsapp_config()
    provider = cfg["provider"]
    url = cfg["url"]
    key = cfg["key"]
    instance = cfg["instance"]

    headers = {"Content-Type": "application/json"}
    if key:
        headers["apikey"] = key
        headers["Authorization"] = f"Bearer {key}"
        headers["api_key"] = key

    b64_data = base64.b64encode(pdf_bytes).decode("utf-8")

    try:
        with httpx.Client(timeout=45.0, verify=False) as client:

            # ── 1. Evolution API ───────────────────────────────────────────
            if provider == "evolution":
                number = normalize_whatsapp_number(to, for_evolution=True)
                if not number:
                    raise ValueError("Número de WhatsApp destinatario vacío o inválido")

                payload = {
                    "number": number,
                    "mediatype": "document",
                    "mimetype": "application/pdf",
                    "caption": caption or "Boletín Ejecutivo — Universidad de La Sabana",
                    "media": b64_data,
                    "fileName": filename
                }
                endpoint = f"{url}/message/sendMedia/{instance}"
                resp = client.post(endpoint, json=payload, headers=headers)

                if resp.status_code in (200, 201):
                    data = resp.json()
                    msg_id = data.get("key", {}).get("id") or str(data.get("id", ""))
                    return {"success": True, "id": msg_id, "chat_id": number, "error": ""}
                else:
                    return {
                        "success": False,
                        "id": "",
                        "chat_id": number,
                        "error": f"Evolution API HTTP {resp.status_code}: {resp.text}"
                    }

            # ── 2. Open-Wa ─────────────────────────────────────────────────
            else:
                chat_id = normalize_whatsapp_number(to, for_evolution=False)
                if not chat_id:
                    raise ValueError("Número de WhatsApp destinatario vacío o inválido")

                payload = {
                    "to": chat_id,
                    "chatId": chat_id,
                    "file": f"data:application/pdf;base64,{b64_data}",
                    "filename": filename,
                    "caption": caption or "Boletín Ejecutivo — Universidad de La Sabana"
                }
                resp = client.post(f"{url}/sendFile", json=payload, headers=headers)

                if resp.status_code in (200, 201):
                    data = resp.json()
                    msg_id = str(data.get("response", data.get("id", ""))) if isinstance(data, dict) else str(data)
                    return {"success": True, "id": msg_id, "chat_id": chat_id, "error": ""}
                else:
                    return {
                        "success": False,
                        "id": "",
                        "chat_id": chat_id,
                        "error": f"Open-Wa HTTP {resp.status_code}: {resp.text}"
                    }

    except (httpx.ConnectError, ConnectionRefusedError):
        return {
            "success": False,
            "id": "",
            "chat_id": to,
            "error": f"No fue posible conectar con el servidor de WhatsApp en '{url}'."
        }
    except Exception as e:
        return {"success": False, "id": "", "chat_id": to, "error": str(e)}

