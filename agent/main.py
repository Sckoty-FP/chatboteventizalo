# agent/main.py — Servidor FastAPI + Webhook de WhatsApp
# Generado por AgentKit

import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv

from agent.brain import generar_respuesta
from agent.memory import inicializar_db, guardar_mensaje, obtener_historial
from agent.providers import obtener_proveedor

load_dotenv()

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
logging.basicConfig(level=logging.DEBUG if ENVIRONMENT == "development" else logging.INFO)
logger = logging.getLogger("agentkit")

proveedor = obtener_proveedor()
PORT = int(os.getenv("PORT", 8000))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await inicializar_db()
    logger.info(f"AgentKit corriendo en puerto {PORT}")
    logger.info(f"Proveedor: {proveedor.__class__.__name__}")
    yield


app = FastAPI(title="Aura — Agente WhatsApp de Eventízalo", version="1.0.0", lifespan=lifespan)


@app.get("/")
async def root():
    return {"status": "ok", "agente": "Aura", "negocio": "Eventízalo"}


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/webhook")
async def webhook_verificacion(request: Request):
    """Verificación GET del webhook (Meta Cloud API)."""
    resultado = await proveedor.validar_webhook(request)
    if resultado is not None:
        return PlainTextResponse(str(resultado))
    return {"status": "ok"}


@app.post("/webhook")
async def webhook_handler(request: Request):
    """Recibe mensajes de WhatsApp, genera respuesta con Claude y la envía."""
    try:
        mensajes = await proveedor.parsear_webhook(request)

        for msg in mensajes:
            if msg.es_propio or not msg.texto:
                continue

            logger.info(f"[{msg.telefono}] → {msg.texto}")

            historial = await obtener_historial(msg.telefono)
            respuesta = await generar_respuesta(msg.texto, historial)

            await guardar_mensaje(msg.telefono, "user", msg.texto)
            await guardar_mensaje(msg.telefono, "assistant", respuesta)

            await proveedor.enviar_mensaje(msg.telefono, respuesta)
            logger.info(f"[{msg.telefono}] ← {respuesta[:80]}...")

        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Error en webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))
