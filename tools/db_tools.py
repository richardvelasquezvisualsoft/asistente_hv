import logging
from datetime import datetime, date
from typing import Optional, Dict, Any, List
from sqlalchemy import text
from core.database import obtener_sesion_hv, obtener_sesion_rag

logger = logging.getLogger(__name__)

async def analizar_texto_completo(texto: str) -> Dict[str, Any]:
    """
    Llama a la función SQL fn_analizar_texto_completo(texto)
    que normaliza el texto, clasifica la intención primaria, y detecta fecha, invitados y ambiente.
    """
    query = text("SELECT * FROM fn_analizar_texto_completo(:texto)")
    async with obtener_sesion_hv() as sesion:
        try:
            resultado = await sesion.execute(query, {"texto": texto})
            fila = resultado.fetchone()
            if fila:
                # Retorna un diccionario con los campos mapeados
                return {
                    "texto_tratado": fila[0],         # p_texto_tratado
                    "categoria": fila[1],             # p_categoria_final
                    "fecha_iso": fila[2],             # p_fecha_detectada
                    "ambiente_detectado": fila[3],    # p_ambiente_detectado
                    "invitados_detectados": fila[4],  # p_invitados_detectados
                    "error": None
                }
        except Exception as e:
            logger.error(f"Error al ejecutar fn_analizar_texto_completo: {e}")
            error_msg = str(e)
        
        # Fallback si falla
        return {
            "texto_tratado": texto,
            "categoria": "SIN_CATEGORIA",
            "fecha_iso": "VACIO",
            "ambiente_detectado": "VACIO",
            "invitados_detectados": "VACIO",
            "error": error_msg if 'error_msg' in locals() else "Resultado vacío"
        }

async def obtener_precio_evento(fecha_iso: str, ambiente: str, invitados: int) -> Optional[int]:
    """
    Llama a la función SQL public.fnObtienePrecio(fecha, ambiente, invitados)
    para calcular el precio referencial del evento.
    """
    query = text("SELECT public.fnObtienePrecio(CAST(:fecha AS DATE), CAST(:ambiente AS TEXT), CAST(:invitados AS INTEGER)) AS precio")
    async with obtener_sesion_hv() as sesion:
        try:
            from datetime import datetime
            fecha_date = datetime.strptime(fecha_iso, "%Y-%m-%d").date()

            # Normalizar nombres de ambientes a lo que espera la base de datos
            # n8n mapea: 'SALON_CERRADO' -> 'SALON CERRADO', etc.
            ambiente_db = ambiente
            if ambiente == "SALON_CERRADO":
                ambiente_db = "SALON CERRADO"
            elif ambiente == "AMBIENTE_JARDIN":
                ambiente_db = "AMBIENTE DE JARDIN"
            elif ambiente == "AMBOS_AMBIENTES":
                ambiente_db = "AMBOS AMBIENTES"

            resultado = await sesion.execute(query, {
                "fecha": fecha_date,
                "ambiente": ambiente_db,
                "invitados": invitados
            })
            fila = resultado.fetchone()
            if fila and fila[0] is not None:
                return int(fila[0])
        except Exception as e:
            logger.error(f"Error al calcular precio usando fnObtienePrecio: {e}")
        return None

async def obtener_estado_sesion(phone_number: str) -> Dict[str, Any]:
    """
    Consulta las variables guardadas en la sesión activa del usuario.
    """
    query = text(
        "SELECT fecha_iso, ambiente, invitados, sin_categoria, disponibilidad_fecha "
        "FROM hv_estado_sesion WHERE phone_number = :phone_number"
    )
    async with obtener_sesion_hv() as sesion:
        try:
            resultado = await sesion.execute(query, {"phone_number": phone_number})
            fila = resultado.fetchone()
            if fila:
                # Mapeo a formato esperado por el flujo de negocio
                fecha_val = fila[0]
                if isinstance(fecha_val, (date, datetime)):
                    fecha_str = fecha_val.strftime("%Y-%m-%d")
                else:
                    fecha_str = str(fecha_val) if fecha_val else "VACIO"

                return {
                    "Sesion_FechaISO": fecha_str,
                    "Sesion_Ambiente": fila[1] if fila[1] else "VACIO",
                    "Sesion_Invitados": str(fila[2]) if fila[2] is not None else "VACIO",
                    "Sesion_Sin_Categoria": fila[3] if fila[3] is not None else 0,
                    "Sesion_Disponibilidad_Fecha": fila[4] if fila[4] else "VACIO"
                }
        except Exception as e:
            logger.error(f"Error al obtener estado de sesión para {phone_number}: {e}")
        
        return {
            "Sesion_FechaISO": "VACIO",
            "Sesion_Ambiente": "VACIO",
            "Sesion_Invitados": "VACIO",
            "Sesion_Sin_Categoria": 0,
            "Sesion_Disponibilidad_Fecha": "VACIO"
        }

async def actualizar_ambiente_sesion(phone_number: str, ambiente: str):
    """Guarda el ambiente seleccionado en el estado de la sesión."""
    query = text(
        "INSERT INTO hv_estado_sesion (phone_number, ambiente, updated_at) "
        "VALUES (:phone_number, :ambiente, now()) "
        "ON CONFLICT (phone_number) DO UPDATE SET "
        "ambiente = EXCLUDED.ambiente, updated_at = now()"
    )
    async with obtener_sesion_hv() as sesion:
        await sesion.execute(query, {"phone_number": phone_number, "ambiente": ambiente})

async def actualizar_fecha_sesion(phone_number: str, fecha_iso: str):
    """Guarda la fecha seleccionada en el estado de la sesión."""
    val_fecha = None
    if fecha_iso and fecha_iso != "VACIO":
        try:
            val_fecha = datetime.strptime(fecha_iso, "%Y-%m-%d").date()
        except ValueError:
            val_fecha = None
    query = text(
        "INSERT INTO hv_estado_sesion (phone_number, fecha_iso, updated_at) "
        "VALUES (:phone_number, :fecha, now()) "
        "ON CONFLICT (phone_number) DO UPDATE SET "
        "fecha_iso = EXCLUDED.fecha_iso, updated_at = now()"
    )
    async with obtener_sesion_hv() as sesion:
        await sesion.execute(query, {"phone_number": phone_number, "fecha": val_fecha})

async def actualizar_invitados_sesion(phone_number: str, invitados: int):
    """Guarda la cantidad de invitados en el estado de la sesión, infiriendo el ambiente si es necesario."""
    query = text(
        "INSERT INTO hv_estado_sesion (phone_number, invitados, updated_at) "
        "VALUES (:phone_number, :invitados, now()) "
        "ON CONFLICT (phone_number) DO UPDATE SET "
        "invitados = EXCLUDED.invitados, updated_at = now()"
    )
    async with obtener_sesion_hv() as sesion:
        await sesion.execute(query, {"phone_number": phone_number, "invitados": invitados})
        
        # Inferir ambiente de forma inteligente según aforo si está vacío
        if invitados > 180:
            query_check = text("SELECT ambiente FROM hv_estado_sesion WHERE phone_number = :phone_number")
            res = await sesion.execute(query_check, {"phone_number": phone_number})
            fila = res.fetchone()
            current_ambiente = fila[0] if fila else None
            
            if not current_ambiente or current_ambiente in ["VACIO", ""]:
                nuevo_ambiente = "AMBIENTE_JARDIN" if invitados <= 300 else "AMBOS_AMBIENTES"
                query_update_amb = text(
                    "UPDATE hv_estado_sesion SET ambiente = :amb, updated_at = now() WHERE phone_number = :phone_number"
                )
                await sesion.execute(query_update_amb, {"phone_number": phone_number, "amb": nuevo_ambiente})

async def actualizar_disponibilidad_sesion(phone_number: str, disponibilidad: str):
    """Guarda el estado de disponibilidad verificado (DISPONIBLE / NO_DISPONIBLE)."""
    query = text(
        "INSERT INTO hv_estado_sesion (phone_number, disponibilidad_fecha, updated_at) "
        "VALUES (:phone_number, :disponibilidad, now()) "
        "ON CONFLICT (phone_number) DO UPDATE SET "
        "disponibilidad_fecha = EXCLUDED.disponibilidad_fecha, updated_at = now()"
    )
    async with obtener_sesion_hv() as sesion:
        await sesion.execute(query, {"phone_number": phone_number, "disponibilidad": disponibilidad})

async def incrementar_sin_categoria(phone_number: str) -> int:
    """Incrementa en 1 el contador de fallos consecutivas sin intención clara del usuario."""
    query = text(
        "INSERT INTO hv_estado_sesion (phone_number, sin_categoria, updated_at) "
        "VALUES (:phone_number, 1, now()) "
        "ON CONFLICT (phone_number) "
        "DO UPDATE SET sin_categoria = COALESCE(hv_estado_sesion.sin_categoria, 0) + 1, updated_at = now() "
        "RETURNING sin_categoria"
    )
    async with obtener_sesion_hv() as sesion:
        resultado = await sesion.execute(query, {"phone_number": phone_number})
        fila = resultado.fetchone()
        return fila[0] if fila else 1

async def reestablecer_sin_categoria(phone_number: str):
    """Reinicia el contador de sin_categoria cuando el usuario formula una petición válida."""
    query = text(
        "UPDATE hv_estado_sesion SET sin_categoria = 0, updated_at = now() WHERE phone_number = :phone_number"
    )
    async with obtener_sesion_hv() as sesion:
        await sesion.execute(query, {"phone_number": phone_number})

async def verificar_atencion_humana_activa(phone_number: str) -> int:
    """Verifica si el usuario tiene una solicitud de atención humana en curso en la BD."""
    query = text("SELECT COUNT(*) FROM hv_atencion_agentes WHERE usuario_ws = :phone_number")
    async with obtener_sesion_hv() as sesion:
        resultado = await sesion.execute(query, {"phone_number": phone_number})
        fila = resultado.fetchone()
        return fila[0] if fila else 0

async def obtener_asignacion_humana(phone_number: str) -> Optional[Dict[str, Any]]:
    """
    Retorna la asignación activa de un cliente con un agente humano.
    Permite el enrutamiento bidireccional (forwarding) de mensajes cliente <-> asesor.
    """
    query = text(
        "SELECT "
        "  CASE "
        "    WHEN usuario_ws = :phone_number THEN 'CLIENTE' "
        "    WHEN agente_humano = :phone_number THEN 'AGENTE' "
        "    ELSE 'DESCONOCIDO' "
        "  END AS tipo_numero, "
        "  CASE "
        "    WHEN usuario_ws = :phone_number THEN agente_humano "
        "    WHEN agente_humano = :phone_number THEN usuario_ws "
        "    ELSE NULL "
        "  END AS numero_destino, "
        "  usuario_ws, agente_humano, agente_ai, estado "
        "FROM public.hv_atencion_agentes "
        "WHERE estado = 'ASIGNADO' AND (usuario_ws = :phone_number OR agente_humano = :phone_number) "
        "ORDER BY created_at DESC LIMIT 1"
    )
    async with obtener_sesion_hv() as sesion:
        resultado = await sesion.execute(query, {"phone_number": phone_number})
        fila = resultado.fetchone()
        if fila and fila[1] is not None:
            return {
                "tipo_numero": fila[0],
                "numero_destino": fila[1],
                "usuario_ws": fila[2],
                "agente_humano": fila[3],
                "agente_ai": fila[4],
                "estado": fila[5]
            }
        return None

async def crear_solicitud_atencion_humana(phone_number: str, display_phone_number: str):
    """Crea un registro de atención humana en estado 'PENDIENTE' para que un asesor pueda tomarlo."""
    query = text(
        "INSERT INTO public.hv_atencion_agentes (usuario_ws, agente_ai, estado, mensaje, created_at) "
        "VALUES (:phone_number, :display_phone_number, 'PENDIENTE', 'Resumen de la Conversacion', now())"
    )
    async with obtener_sesion_hv() as sesion:
        await sesion.execute(query, {
            "phone_number": phone_number,
            "display_phone_number": display_phone_number
        })

async def eliminar_atencion_humana(phone_number: str):
    """Elimina la solicitud o asignación de atención humana (ej. si el usuario escribe 'AGENTE')."""
    query = text("DELETE FROM hv_atencion_agentes WHERE usuario_ws = :phone_number")
    async with obtener_sesion_hv() as sesion:
        await sesion.execute(query, {"phone_number": phone_number})

async def asignar_agente_humano_libre(agente_humano: str):
    """
    Simula la aceptación de un agente humano presionando un botón.
    Asigna el agente a la solicitud PENDIENTE más antigua en cola.
    """
    query = text(
        "UPDATE public.hv_atencion_agentes "
        "SET agente_humano = :agente_humano, estado = 'ASIGNADO', mensaje = 'ACEPTO', updated_at = now() "
        "WHERE usuario_ws = ("
        "  SELECT usuario_ws FROM public.hv_atencion_agentes "
        "  WHERE estado = 'PENDIENTE' "
        "  ORDER BY created_at ASC LIMIT 1"
        ")"
    )
    async with obtener_sesion_hv() as sesion:
        await sesion.execute(query, {"agente_humano": agente_humano})

async def obtener_todos_los_agentes() -> List[Dict[str, Any]]:
    """Consulta la lista de asesores humanos configurados en la base de datos."""
    query = text("SELECT agente_humano, nombre FROM hv_agentes")
    async with obtener_sesion_hv() as sesion:
        resultado = await sesion.execute(query)
        filas = resultado.fetchall()
        return [{"agente_humano": f[0], "nombre": f[1]} for f in filas]

async def contar_mensajes_historial(phone_number: str) -> int:
    """Cuenta los mensajes almacenados en el historial de chat para este usuario."""
    query = text("SELECT COALESCE(COUNT(*), 0) FROM n8n_chat_histories WHERE session_id = :phone_number")
    async with obtener_sesion_rag() as sesion:
        resultado = await sesion.execute(query, {"phone_number": phone_number})
        fila = resultado.fetchone()
        return fila[0] if fila else 0

async def bot_se_presento(phone_number: str) -> bool:
    """Verifica si el bot ya se presentó o envió algún mensaje al usuario."""
    query = text(
        "SELECT COUNT(*) FROM n8n_chat_histories "
        "WHERE session_id = :phone_number AND CAST(message AS text) LIKE '%assistant%'"
    )
    async with obtener_sesion_rag() as sesion:
        resultado = await sesion.execute(query, {"phone_number": phone_number})
        fila = resultado.fetchone()
        return (fila[0] > 0) if fila else False

async def guardar_mensaje_historial(phone_number: str, mensaje_json: str):
    """Guarda un mensaje en la tabla de historial de chat."""
    query = text(
        "INSERT INTO n8n_chat_histories (session_id, message, created_at) "
        "VALUES (:phone_number, :message, now())"
    )
    async with obtener_sesion_rag() as sesion:
        await sesion.execute(query, {
            "phone_number": phone_number,
            "message": mensaje_json
        })

async def obtener_historial_chat(phone_number: str, limit: int = 15) -> List[Dict[str, Any]]:
    """Obtiene los últimos N mensajes del historial de chat para el usuario."""
    import json
    query = text(
        "SELECT message FROM n8n_chat_histories "
        "WHERE session_id = :phone_number "
        "ORDER BY created_at DESC LIMIT :limit"
    )
    async with obtener_sesion_rag() as sesion:
        resultado = await sesion.execute(query, {"phone_number": phone_number, "limit": limit})
        filas = resultado.fetchall()
        
        historial = []
        for fila in filas:
            try:
                raw_val = fila[0]
                if isinstance(raw_val, dict):
                    d = raw_val
                elif isinstance(raw_val, str):
                    d = json.loads(raw_val)
                else:
                    d = {}
                
                if "message" in d:
                    d["content"] = d.pop("message")
                
                if d:
                    historial.append(d)
            except Exception as e:
                pass
        # Invertir para que el orden sea cronológico (el más antiguo primero)
        historial.reverse()
        return historial

async def reiniciar_estado_sesion(phone_number: str):
    """
    Elimina las variables guardadas en la sesión y borra el historial de chat para reiniciar las pruebas.
    """
    query_session = text("DELETE FROM hv_estado_sesion WHERE phone_number = :phone_number")
    query_history = text("DELETE FROM n8n_chat_histories WHERE session_id = :phone_number")
    query_human = text("DELETE FROM hv_atencion_agentes WHERE usuario_ws = :phone_number")

    async with obtener_sesion_hv() as sesion_hv:
        await sesion_hv.execute(query_session, {"phone_number": phone_number})
        await sesion_hv.execute(query_human, {"phone_number": phone_number})

    async with obtener_sesion_rag() as sesion_rag:
        await sesion_rag.execute(query_history, {"phone_number": phone_number})

async def obtener_modo_bot_global() -> str:
    """Obtiene el estado de atención global del bot ('BOT_ACTIVO' o 'BOT_DESACTIVADO')."""
    query = text("SELECT valor FROM hv_prompt_config WHERE clave = 'BOT_MODO_GLOBAL'")
    async with obtener_sesion_hv() as sesion:
        res = await sesion.execute(query)
        fila = res.fetchone()
        return fila[0] if fila and fila[0] else 'BOT_ACTIVO'

async def cambiar_modo_bot_global(nuevo_modo: str) -> bool:
    """Modifica el estado de atención global del bot."""
    query = text(
        "INSERT INTO hv_prompt_config (clave, valor) VALUES ('BOT_MODO_GLOBAL', :val) "
        "ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor"
    )
    async with obtener_sesion_hv() as sesion:
        await sesion.execute(query, {"val": nuevo_modo})
        return True

async def obtener_modo_atencion_usuario(phone_number: str) -> str:
    """Obtiene el modo de atención individual del usuario ('BOT' o 'HUMANO')."""
    query = text("SELECT modo_atencion FROM hv_estado_sesion WHERE phone_number = :phone_number")
    async with obtener_sesion_hv() as sesion:
        res = await sesion.execute(query, {"phone_number": phone_number})
        fila = res.fetchone()
        return fila[0] if fila and fila[0] else 'BOT'

async def cambiar_modo_atencion_usuario(phone_number: str, modo: str) -> bool:
    """Cambia el modo de atención individual de un usuario específico ('BOT' o 'HUMANO')."""
    query = text(
        "INSERT INTO hv_estado_sesion (phone_number, modo_atencion, updated_at) "
        "VALUES (:phone_number, :modo, now()) "
        "ON CONFLICT (phone_number) DO UPDATE SET modo_atencion = :modo, updated_at = now()"
    )
    async with obtener_sesion_hv() as sesion:
        await sesion.execute(query, {"phone_number": phone_number, "modo": modo})
        return True

