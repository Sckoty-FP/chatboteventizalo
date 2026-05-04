# agent/brain.py — Cerebro del agente con Claude Tool Use
# Generado por AgentKit

import os
import json
import yaml
import logging
from anthropic import AsyncAnthropic
from dotenv import load_dotenv

from agent.tools import (
    verificar_disponibilidad,
    registrar_lead,
    buscar_o_crear_cliente,
    crear_evento,
    obtener_eventos_proximos,
)

load_dotenv()
logger = logging.getLogger("agentkit")

client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# ── Definición de herramientas para Claude ───────────────────

TOOLS = [
    {
        "name": "verificar_disponibilidad",
        "description": "Verifica si una fecha específica tiene disponibilidad para un nuevo evento. Usá esta herramienta cuando el cliente mencione una fecha.",
        "input_schema": {
            "type": "object",
            "properties": {
                "fecha": {
                    "type": "string",
                    "description": "Fecha del evento en formato YYYY-MM-DD (ej: 2026-07-23)"
                }
            },
            "required": ["fecha"]
        }
    },
    {
        "name": "registrar_lead",
        "description": "Registra a un cliente interesado en el sistema. Usá esta herramienta cuando tengas al menos el nombre y el interés del cliente, aunque no haya confirmado reserva todavía.",
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre": {"type": "string", "description": "Nombre completo del cliente"},
                "telefono": {"type": "string", "description": "Número de teléfono o WhatsApp"},
                "tipo_evento": {"type": "string", "description": "Tipo de evento: boda, cumpleaños, corporativo, comunión, etc."},
                "fecha_evento": {"type": "string", "description": "Fecha del evento (texto libre está bien)"},
                "servicios": {"type": "string", "description": "Servicios que le interesan"},
                "invitados": {"type": "integer", "description": "Número aproximado de invitados"},
                "zona": {"type": "string", "description": "Zona o ciudad del evento"},
                "notas": {"type": "string", "description": "Cualquier información adicional relevante"}
            },
            "required": ["nombre", "telefono"]
        }
    },
    {
        "name": "crear_reserva_completa",
        "description": "Crea la reserva completa: primero crea o encuentra al cliente, luego crea el evento en el sistema con todos los datos. Usá esta herramienta SOLO cuando el cliente haya confirmado explícitamente que quiere reservar y tenés todos los datos necesarios (nombre, teléfono, fecha, servicio).",
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre_cliente": {"type": "string", "description": "Nombre del cliente"},
                "apellido_cliente": {"type": "string", "description": "Apellido del cliente"},
                "telefono_cliente": {"type": "string", "description": "Teléfono del cliente"},
                "nombre_evento": {"type": "string", "description": "Nombre descriptivo del evento (ej: 'Boda Carla Gómez')"},
                "tipo_evento": {"type": "string", "description": "Tipo: boda, cumpleaños, corporativo, comunión, otro"},
                "fecha_evento": {"type": "string", "description": "Fecha en formato YYYY-MM-DD"},
                "hora_evento": {"type": "string", "description": "Hora en formato HH:MM (ej: 17:00)"},
                "lugar": {"type": "string", "description": "Dirección o descripción del lugar"},
                "precio_total": {"type": "number", "description": "Precio total acordado en euros"},
                "senal_pagada": {"type": "number", "description": "Señal ya pagada (0 si aún no pagó)"},
                "notas": {"type": "string", "description": "Notas del evento. Incluí aquí: DNI del cliente, nombre de los protagonistas (novios/festejado para el diseño), si quieren marca de agua/logo, nombre de quien pagó la señal, y cualquier detalle extra"},
                "dni_cliente": {"type": "string", "description": "DNI del cliente"},
                "protagonistas": {"type": "string", "description": "Nombre de los protagonistas del evento (novios, festejado...) para el diseño"},
                "marca_agua": {"type": "string", "description": "Si quieren marca de agua/logo en fotos y vídeos (sí/no + detalle)"},
                "servicios": {
                    "type": "array",
                    "description": "Lista de servicios contratados",
                    "items": {
                        "type": "object",
                        "properties": {
                            "nombre_clave": {
                                "type": "string",
                                "description": "Clave del servicio: fotomaton, plataforma360, discomovil, cabinavogue"
                            },
                            "precio": {"type": "number", "description": "Precio de ese servicio"}
                        }
                    }
                }
            },
            "required": ["nombre_cliente", "telefono_cliente", "nombre_evento", "fecha_evento", "precio_total"]
        }
    },
]


# ── Ejecutor de herramientas ─────────────────────────────────

def ejecutar_herramienta(nombre: str, parametros: dict) -> str:
    """Ejecuta una herramienta y retorna el resultado como string."""
    try:
        if nombre == "verificar_disponibilidad":
            resultado = verificar_disponibilidad(parametros["fecha"])
            return json.dumps(resultado, ensure_ascii=False)

        elif nombre == "registrar_lead":
            resultado = registrar_lead(
                nombre=parametros.get("nombre", ""),
                telefono=parametros.get("telefono", ""),
                tipo_evento=parametros.get("tipo_evento", ""),
                fecha_evento=parametros.get("fecha_evento", ""),
                servicios=parametros.get("servicios", ""),
                invitados=parametros.get("invitados", 0),
                zona=parametros.get("zona", ""),
                notas=parametros.get("notas", ""),
            )
            return json.dumps(resultado, ensure_ascii=False)

        elif nombre == "crear_reserva_completa":
            # Validar que el teléfono sea real antes de crear nada
            telefono = parametros.get("telefono_cliente", "").strip()
            if not telefono or len(telefono) < 7 or telefono.upper() in ("FALTA", "NO", "NO PROPORCIONADO", "N/A", ""):
                return json.dumps({
                    "exito": False,
                    "mensaje": "No se puede crear la reserva: falta el teléfono del cliente. Pedíselo antes de continuar."
                }, ensure_ascii=False)

            # Paso 1: crear o encontrar el cliente
            id_cliente = buscar_o_crear_cliente(
                nombre=parametros.get("nombre_cliente", ""),
                apellido=parametros.get("apellido_cliente", ""),
                telefono=parametros.get("telefono_cliente", ""),
            )

            # Ensamblar notas completas con todos los datos del formulario
            notas_partes = []
            if parametros.get("notas"):
                notas_partes.append(parametros["notas"])
            if parametros.get("dni_cliente"):
                notas_partes.append(f"DNI: {parametros['dni_cliente']}")
            if parametros.get("protagonistas"):
                notas_partes.append(f"Protagonistas (diseño): {parametros['protagonistas']}")
            if parametros.get("marca_agua"):
                notas_partes.append(f"Marca de agua: {parametros['marca_agua']}")
            notas_final = " | ".join(notas_partes)

            # Paso 2: crear el evento
            resultado = crear_evento(
                nombre_evento=parametros.get("nombre_evento", ""),
                fecha_evento=parametros.get("fecha_evento", ""),
                hora_evento=parametros.get("hora_evento", ""),
                lugar=parametros.get("lugar", ""),
                tipo_evento=parametros.get("tipo_evento", ""),
                precio_total=parametros.get("precio_total", 0),
                senal_pagada=parametros.get("senal_pagada", 0),
                notas=notas_final,
                id_cliente=id_cliente,
                servicios=parametros.get("servicios", []),
            )
            resultado["id_cliente"] = id_cliente
            return json.dumps(resultado, ensure_ascii=False)

        else:
            return json.dumps({"error": f"Herramienta desconocida: {nombre}"})

    except Exception as e:
        logger.error(f"Error ejecutando herramienta {nombre}: {e}")
        return json.dumps({"error": str(e)})


# ── Carga de configuración ───────────────────────────────────

def cargar_config_prompts() -> dict:
    try:
        with open("config/prompts.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.error("config/prompts.yaml no encontrado")
        return {}


def cargar_system_prompt() -> str:
    config = cargar_config_prompts()
    return config.get("system_prompt", "Eres Aura, asistente de Eventízalo. Respondé en español.")


def obtener_mensaje_error() -> str:
    config = cargar_config_prompts()
    return config.get("error_message", "¡Ups! Estoy teniendo un problema técnico. Intentá de nuevo en unos minutos 😊")


def obtener_mensaje_fallback() -> str:
    config = cargar_config_prompts()
    return config.get("fallback_message", "Disculpá, no entendí bien. ¿Me podés contar un poco más? 😊")


# ── Generación de respuesta con tool use ─────────────────────

async def generar_respuesta(mensaje: str, historial: list[dict]) -> str:
    """
    Genera una respuesta usando Claude con soporte de herramientas.
    Maneja el ciclo completo: respuesta → tool_use → resultado → respuesta final.
    """
    if not mensaje or len(mensaje.strip()) < 2:
        return obtener_mensaje_fallback()

    system_prompt = cargar_system_prompt()

    # Construir mensajes para la API
    mensajes = [{"role": m["role"], "content": m["content"]} for m in historial]
    mensajes.append({"role": "user", "content": mensaje})

    try:
        # Ciclo de tool use: máximo 5 iteraciones para evitar loops infinitos
        for _ in range(5):
            response = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                system=system_prompt,
                tools=TOOLS,
                messages=mensajes,
            )

            # Si Claude termina sin usar herramientas → retornar texto
            if response.stop_reason == "end_turn":
                for bloque in response.content:
                    if hasattr(bloque, "text"):
                        logger.info(f"Tokens: {response.usage.input_tokens} in / {response.usage.output_tokens} out")
                        return bloque.text
                return obtener_mensaje_fallback()

            # Si Claude quiere usar herramientas
            if response.stop_reason == "tool_use":
                # Agregar la respuesta de Claude (con los tool_use blocks) al historial
                mensajes.append({"role": "assistant", "content": response.content})

                # Ejecutar cada herramienta solicitada
                resultados_tools = []
                for bloque in response.content:
                    if bloque.type == "tool_use":
                        logger.info(f"Herramienta: {bloque.name} | Params: {bloque.input}")
                        resultado = ejecutar_herramienta(bloque.name, bloque.input)
                        logger.info(f"Resultado: {resultado}")
                        resultados_tools.append({
                            "type": "tool_result",
                            "tool_use_id": bloque.id,
                            "content": resultado,
                        })

                # Agregar los resultados al historial y continuar el ciclo
                mensajes.append({"role": "user", "content": resultados_tools})
                continue

            # stop_reason inesperado
            break

        return obtener_mensaje_error()

    except Exception as e:
        logger.error(f"Error Claude API: {e}")
        return obtener_mensaje_error()
