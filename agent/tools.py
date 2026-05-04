# agent/tools.py — Herramientas de Eventízalo integradas con Supabase
# Generado por AgentKit

import os
import logging
from datetime import datetime, date
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("agentkit")

# Cliente Supabase (service role — acceso total)
_sb: Client | None = None

def get_supabase() -> Client:
    global _sb
    if _sb is None:
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_SERVICE_KEY")
        if not url or not key:
            raise ValueError("SUPABASE_URL o SUPABASE_SERVICE_KEY no configurados en .env")
        _sb = create_client(url, key)
    return _sb


# ── INVENTARIO DE EQUIPOS ────────────────────────────────────

INVENTARIO = {
    "fotomaton":    2,  # 2 fotomatones disponibles
    "plataforma360": 2, # 2 plataformas 360
    "discomovil":   1,
    "cabinavogue":  1,
}

MAPEO_NOMBRES = {
    "fotomaton":     "Fotomatón",
    "plataforma360": "Plataforma 360",
    "discomovil":    "Disco Móvil",
    "cabinavogue":   "Cabina Vogue",
}

MAX_EVENTOS_DIA = 4  # máximo de eventos simultáneos en un día


# ── SERVICIOS ────────────────────────────────────────────────

def obtener_id_servicio(nombre_clave: str) -> int | None:
    """Busca el id_servicio por nombre en Supabase."""
    try:
        sb = get_supabase()
        nombre = MAPEO_NOMBRES.get(nombre_clave, nombre_clave)
        res = sb.from_("servicio").select("id_servicio").ilike("nombre", f"%{nombre}%").execute()
        if res.data:
            return res.data[0]["id_servicio"]
    except Exception as e:
        logger.error(f"Error buscando servicio {nombre_clave}: {e}")
    return None


# ── DISPONIBILIDAD ───────────────────────────────────────────

def verificar_disponibilidad(fecha: str) -> dict:
    """
    Verifica disponibilidad real por inventario de equipos.
    Nunca dice que no hay fecha disponible — informa qué servicios quedan libres.
    fecha: formato YYYY-MM-DD
    Retorna: {
        eventos_ese_dia: int,
        servicios_disponibles: dict,   # {servicio: unidades_libres}
        servicios_agotados: list,
        puede_atender: bool,
        mensaje: str
    }
    """
    try:
        sb = get_supabase()

        # Obtener eventos activos en esa fecha con sus servicios
        res = sb.from_("evento").select(
            "id_evento,hora_evento,estado,evento_servicio(id_servicio,servicio(nombre))"
        ).eq("fecha_evento", fecha).in_("estado", ["confirmado", "pendiente"]).execute()

        eventos = res.data or []
        total_eventos = len(eventos)

        # Contar unidades de cada servicio ya reservadas
        usados = {k: 0 for k in INVENTARIO}
        for ev in eventos:
            for es in (ev.get("evento_servicio") or []):
                nombre_svc = (es.get("servicio") or {}).get("nombre", "").lower()
                for clave, nombre_mapeo in MAPEO_NOMBRES.items():
                    if nombre_mapeo.lower() in nombre_svc:
                        usados[clave] = usados.get(clave, 0) + 1

        # Calcular disponibles
        disponibles = {}
        agotados = []
        for clave, total in INVENTARIO.items():
            libres = total - usados.get(clave, 0)
            if libres > 0:
                disponibles[clave] = libres
            else:
                agotados.append(MAPEO_NOMBRES[clave])

        puede_atender = len(disponibles) > 0 and total_eventos < MAX_EVENTOS_DIA

        # Construir mensaje descriptivo
        if total_eventos == 0:
            mensaje = f"La fecha {fecha} está completamente libre 🎉"
        elif not agotados:
            nombres_disp = [MAPEO_NOMBRES[k] for k in disponibles]
            mensaje = f"El {fecha} ya tenemos {total_eventos} evento(s) pero todos los equipos siguen disponibles: {', '.join(nombres_disp)}."
        elif disponibles:
            nombres_disp = [MAPEO_NOMBRES[k] for k in disponibles]
            mensaje = (
                f"El {fecha} ya tenemos {total_eventos} evento(s). "
                f"Equipos disponibles: {', '.join(nombres_disp)}. "
                f"Equipos sin stock ese día: {', '.join(agotados)}."
            )
        else:
            mensaje = (
                f"El {fecha} tenemos todos los equipos comprometidos. "
                "Dependiendo del horario podría ser posible — te recomiendo que lo consultemos."
            )

        return {
            "eventos_ese_dia": total_eventos,
            "servicios_disponibles": disponibles,
            "servicios_agotados": agotados,
            "puede_atender": puede_atender,
            "mensaje": mensaje,
        }

    except Exception as e:
        logger.error(f"Error verificando disponibilidad: {e}")
        return {
            "eventos_ese_dia": 0,
            "servicios_disponibles": {k: v for k, v in INVENTARIO.items()},
            "servicios_agotados": [],
            "puede_atender": True,
            "mensaje": "No pude verificar la disponibilidad exacta, pero en principio deberíamos poder atenderte. Te confirmo en breve.",
        }


# ── LEADS ────────────────────────────────────────────────────

def registrar_lead(
    nombre: str,
    telefono: str,
    tipo_evento: str = "",
    fecha_evento: str = "",
    servicios: str = "",
    invitados: int = 0,
    zona: str = "",
    notas: str = ""
) -> dict:
    """
    Registra un lead en la tabla 'lead' de Supabase.
    Retorna: {exito: bool, id_lead: int | None, mensaje: str}
    """
    try:
        sb = get_supabase()
        payload = {
            "estado": "solicitado",
            "created_at": datetime.utcnow().isoformat(),
            "nombre": nombre,
            "telefono": telefono,
            "tipo_evento": tipo_evento or None,
            "fecha_evento": fecha_evento or None,
            "servicios": servicios or None,
            "invitados": invitados or None,
            "zona": zona or None,
            "notas": notas or None,
        }

        res = sb.from_("lead").insert(payload).execute()
        if res.data:
            return {"exito": True, "id_lead": res.data[0].get("id_lead"), "mensaje": "Lead registrado correctamente"}
        return {"exito": False, "id_lead": None, "mensaje": "No se pudo registrar el lead"}
    except Exception as e:
        logger.error(f"Error registrando lead: {e}")
        return {"exito": False, "id_lead": None, "mensaje": str(e)}


# ── CLIENTES ─────────────────────────────────────────────────

def buscar_o_crear_cliente(nombre: str, apellido: str, telefono: str) -> int | None:
    """
    Busca un cliente por teléfono. Si no existe, lo crea.
    Retorna: id_cliente o None si falla.
    """
    try:
        sb = get_supabase()
        # Buscar por teléfono (normalizar quitando espacios y +)
        tel_limpio = telefono.replace(" ", "").replace("+", "")
        res = sb.from_("cliente").select("id_cliente").ilike("telefono", f"%{tel_limpio}%").execute()
        if res.data:
            return res.data[0]["id_cliente"]

        # Crear cliente nuevo
        nuevo = sb.from_("cliente").insert({
            "nombre": nombre,
            "apellido": apellido,
            "telefono": telefono,
        }).execute()
        if nuevo.data:
            return nuevo.data[0]["id_cliente"]
    except Exception as e:
        logger.error(f"Error buscando/creando cliente: {e}")
    return None


# ── EVENTOS ──────────────────────────────────────────────────

def crear_evento(
    nombre_evento: str,
    fecha_evento: str,
    hora_evento: str,
    lugar: str,
    tipo_evento: str,
    precio_total: float,
    senal_pagada: float,
    notas: str,
    id_cliente: int | None,
    servicios: list[dict]  # [{"nombre_clave": "fotomaton", "precio": 250}, ...]
) -> dict:
    """
    Crea un evento completo en Supabase con sus servicios vinculados.
    Retorna: {exito: bool, id_evento: int | None, mensaje: str}
    """
    try:
        sb = get_supabase()

        payload = {
            "nombre_evento": nombre_evento,
            "tipo_evento": tipo_evento,
            "fecha_evento": fecha_evento,
            "hora_evento": hora_evento or None,
            "lugar": lugar,
            "id_cliente": id_cliente,
            "estado": "pendiente",
            "precio_total": precio_total,
            "senal_pagada": senal_pagada,
            "pago_completado": False,
            "notas": notas,
        }

        res = sb.from_("evento").insert(payload).execute()
        if not res.data:
            return {"exito": False, "id_evento": None, "mensaje": "Error al crear el evento"}

        id_evento = res.data[0]["id_evento"]

        # Vincular servicios
        for svc in servicios:
            id_servicio = obtener_id_servicio(svc.get("nombre_clave", ""))
            if id_servicio:
                sb.from_("evento_servicio").insert({
                    "id_evento": id_evento,
                    "id_servicio": id_servicio,
                    "cantidad": 1,
                    "precio_unitario": svc.get("precio", 0),
                }).execute()

        logger.info(f"Evento creado: id={id_evento}, nombre={nombre_evento}")
        return {"exito": True, "id_evento": id_evento, "mensaje": f"Evento '{nombre_evento}' creado con éxito (ID: {id_evento})"}

    except Exception as e:
        logger.error(f"Error creando evento: {e}")
        return {"exito": False, "id_evento": None, "mensaje": str(e)}


# ── SEGUIMIENTO POST-VENTA ───────────────────────────────────

def obtener_eventos_proximos(dias: int = 14) -> list[dict]:
    """
    Retorna eventos confirmados/pendientes en los próximos N días.
    Útil para el seguimiento automático pre-evento.
    """
    try:
        sb = get_supabase()
        hoy = date.today().isoformat()
        res = (
            sb.from_("evento")
            .select("id_evento,nombre_evento,fecha_evento,hora_evento,lugar,id_cliente,estado,cliente(nombre,apellido,telefono)")
            .gte("fecha_evento", hoy)
            .in_("estado", ["confirmado", "pendiente"])
            .order("fecha_evento")
            .execute()
        )
        eventos = res.data or []
        # Filtrar por los próximos N días
        resultado = []
        for e in eventos:
            try:
                delta = (date.fromisoformat(e["fecha_evento"]) - date.today()).days
                if 0 <= delta <= dias:
                    e["dias_restantes"] = delta
                    resultado.append(e)
            except Exception:
                continue
        return resultado
    except Exception as ex:
        logger.error(f"Error obteniendo eventos próximos: {ex}")
        return []
