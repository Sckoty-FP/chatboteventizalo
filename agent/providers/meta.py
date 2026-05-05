# agent/providers/meta.py — Adaptador para Meta Cloud API (WhatsApp Business)

import os
import logging
import httpx
from fastapi import Request
from agent.providers.base import ProveedorWhatsApp, MensajeEntrante

logger = logging.getLogger("agentkit")

GRAPH_URL = "https://graph.facebook.com/v19.0"


class ProveedorMeta(ProveedorWhatsApp):
    """Proveedor de WhatsApp usando Meta Cloud API."""

    def __init__(self):
        self.access_token = os.getenv("META_ACCESS_TOKEN")
        self.phone_number_id = os.getenv("META_PHONE_NUMBER_ID")
        self.verify_token = os.getenv("META_VERIFY_TOKEN")

    async def validar_webhook(self, request: Request):
        """Verificación GET del webhook — Meta envía hub.challenge y hay que devolvérlo."""
        mode = request.query_params.get("hub.mode")
        token = request.query_params.get("hub.verify_token")
        challenge = request.query_params.get("hub.challenge")
        if mode == "subscribe" and token == self.verify_token:
            logger.info("Webhook Meta verificado correctamente")
            return challenge
        logger.warning("Verificación de webhook Meta fallida")
        return None

    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        """Parsea el payload JSON de Meta Cloud API."""
        try:
            body = await request.json()
            mensajes = []
            for entry in body.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value", {})
                    for msg in value.get("messages", []):
                        if msg.get("type") != "text":
                            continue
                        telefono = msg.get("from", "")
                        texto = msg.get("text", {}).get("body", "")
                        mensaje_id = msg.get("id", "")
                        if texto:
                            mensajes.append(MensajeEntrante(
                                telefono=telefono,
                                texto=texto,
                                mensaje_id=mensaje_id,
                                es_propio=False,
                            ))
            return mensajes
        except Exception as e:
            logger.error(f"Error parseando webhook Meta: {e}")
            return []

    async def enviar_mensaje(self, telefono: str, mensaje: str) -> bool:
        """Envía mensaje via Meta Cloud API."""
        if not all([self.access_token, self.phone_number_id]):
            logger.warning("META_ACCESS_TOKEN o META_PHONE_NUMBER_ID no configurados")
            return False
        url = f"{GRAPH_URL}/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": telefono,
            "type": "text",
            "text": {"body": mensaje},
        }
        async with httpx.AsyncClient() as client:
            r = await client.post(url, json=payload, headers=headers)
            if r.status_code != 200:
                logger.error(f"Error Meta API: {r.status_code} — {r.text}")
            return r.status_code == 200
