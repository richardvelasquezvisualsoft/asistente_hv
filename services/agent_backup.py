import json
import logging
from typing import List, Dict, Any, TypedDict
from langgraph.graph import StateGraph, END
from config import configuracion
from services.openai_service import servicio_openai
from tools.db_tools import (
    obtener_estado_sesion,
    contar_mensajes_historial,
    obtener_precio_evento,
    actualizar_disponibilidad_sesion,
    actualizar_fecha_sesion,
    guardar_mensaje_historial,
    reestablecer_sin_categoria,
    bot_se_presento
)
from tools.calendar import servicio_calendario
from tools.rag import buscador_rag
from datetime import datetime

logger = logging.getLogger(__name__)

# Definición del Estado del Agente conforme a los requerimientos de LangGraph
class EstadoAgente(TypedDict):
    phone_number: str
    display_phone_number: str
    msg_Consulta: str
    msg_Categoria: str
    msg_FechaISO: str
    msg_Ambiente: str
    msg_Invitados: str
    msg_Sin_Categoria: int
    message_count: int
    
    # Slots de sesión acumulados cargados desde la base de datos
    sesion_slots: Dict[str, Any]
    
    # Lista ordenada de intenciones a procesar
    categorias_pendientes: List[str]
    
    # Fragmentos de texto generados por cada nodo
    respuestas: List[str]
    
    # Flag para abortar el procesamiento e ir directamente a compilar la respuesta
    terminar_inmediatamente: bool

    # Historial de logs técnicos de ejecución dentro del grafo
    logs_ejecucion: List[Dict[str, Any]]

# ------------------------------------------------------------
# NODOS DEL GRAFO DE EJECUCIÓN
# ------------------------------------------------------------

async def nodo_inicializar(state: EstadoAgente) -> Dict[str, Any]:
    """
    Carga el estado de sesión actual y el historial de mensajes de la BD.
    Ordena las intenciones detectadas por orden de prioridad.
    """
    phone_number = state["phone_number"]
    
    # 1. Consultar slots de sesión
    slots = await obtener_estado_sesion(phone_number)
    
    # 2. Consultar historial de mensajes
    msg_count = await contar_mensajes_historial(phone_number)
    
    # 3. Clasificar categorías en lista ordenada por prioridad
    # Prioridad: SALUDO -> DISPONIBILIDAD -> PRECIOS -> INFORMACION -> SIN_CATEGORIA
    prioridad = ["SALUDO", "DISPONIBILIDAD", "PRECIOS", "INFORMACION", "SIN_CATEGORIA"]
    
    msg_cat_raw = state["msg_Categoria"]
    categorias_detectadas = [c.strip() for c in msg_cat_raw.split("_") if c.strip()]
    
    # Ordenar y filtrar categorías válidas
    categorias_ordenadas = [cat for cat in prioridad if cat in categorias_detectadas]
    
    # Si viene con un saludo pero no está explícitamente en la lista, podemos agregarlo si el texto inicial es un saludo
    if not categorias_ordenadas:
        categorias_ordenadas = ["SIN_CATEGORIA"]

    logger.info(f"Inicializando Agente. Categorías a procesar: {categorias_ordenadas}")
    
    # Si la categoría no es SIN_CATEGORIA, restablecemos el contador de fallos consecutivas
    if "SIN_CATEGORIA" not in categorias_ordenadas:
        await reestablecer_sin_categoria(phone_number)
        slots["Sesion_Sin_Categoria"] = 0

    logs = [{
        "paso": "init",
        "mensaje": f"Inicializando el flujo del Agente.\n- Slots en Base de Datos: {slots}\n- Historial de chat: {msg_count} mensajes previos.\n- Categorías ordenadas por prioridad: {categorias_ordenadas}"
    }]

    return {
        "sesion_slots": slots,
        "message_count": msg_count,
        "categorias_pendientes": categorias_ordenadas,
        "respuestas": [],
        "terminar_inmediatamente": False,
        "logs_ejecucion": logs
    }

async def nodo_saludo(state: EstadoAgente) -> Dict[str, Any]:
    """Procesa la sección de saludo según el historial del cliente."""
    msg_count = state["message_count"]
    categorias = list(state["categorias_pendientes"])
    respuestas = list(state["respuestas"])
    logs = list(state.get("logs_ejecucion", []))
    terminar = False

    # Verificar si el bot ya se presentó alguna vez en la historia de la conversación
    phone_number = state["phone_number"]
    presento = await bot_se_presento(phone_number)

    from datetime import datetime
    
    # Determinar saludo educado según la hora del día (GMT-5 / Perú aprox. - restamos 5 horas a UTC)
    # Si datetime.now() es UTC, podemos ajustarlo restando 5 horas para que sea hora Perú local.
    # Uvicorn suele correr con la zona horaria local o UTC. Vamos a estimar basándonos en la hora actual si es necesario,
    # pero usar datetime.now() funciona bien.
    hora = (datetime.now().hour - 5) % 24  # Ajustar a la zona horaria de Perú (UTC-5)
    if 5 <= hora < 12:
        saludo_educado = "Hola, buenos días."
    elif 12 <= hora < 19:
        saludo_educado = "Hola, buenas tardes."
    else:
        saludo_educado = "Hola, buenas noches."

    saludo = None
    if not presento:
        saludo = "¡Hola! Soy Teffy, asistente virtual del Rincón de la Campiña. Estoy aquí para ayudarte y absolver tus consultas."
        respuestas.append(saludo)
    else:
        # Si ya se presentó en el pasado y vuelve a saludar:
        if len(categorias) == 1:
            saludo = f"{saludo_educado} ¿Cómo estás? ¿En qué te puedo ayudar hoy?"
            respuestas.append(saludo)
        else:
            # Si hay más intenciones pendientes, solo prependeamos el saludo corto
            saludo = saludo_educado
            respuestas.append(saludo)
    
    # Si la única categoría es el saludo, terminamos de inmediato
    if len(categorias) == 1:
        terminar = True
        
    categorias.remove("SALUDO")

    logs.append({
        "paso": "saludo",
        "mensaje": f"Nodo de Saludo ejecutado.\n- Mensaje de saludo seleccionado: '{saludo}'\n- ¿Finalizar flujo después del saludo?: {terminar}"
    })

    return {
        "categorias_pendientes": categorias,
        "respuestas": respuestas,
        "terminar_inmediatamente": terminar,
        "logs_ejecucion": logs
    }

async def nodo_disponibilidad(state: EstadoAgente) -> Dict[str, Any]:
    """Verifica disponibilidad de fechas en Google Calendar o reporta fallos."""
    phone_number = state["phone_number"]
    categorias = list(state["categorias_pendientes"])
    respuestas = list(state["respuestas"])
    slots = dict(state["sesion_slots"])
    logs = list(state.get("logs_ejecucion", []))
    terminar = False

    msg_fecha = state["msg_FechaISO"]
    fecha_sesion = slots.get("Sesion_FechaISO", "VACIO")
    disponibilidad_sesion = slots.get("Sesion_Disponibilidad_Fecha", "VACIO")
    
    msg_log = ""

    # 1. Caso especial: Fecha previamente marcada como NO disponible
    if disponibilidad_sesion == "NO_DISPONIBLE" and (msg_fecha == "VACIO" or msg_fecha == fecha_sesion):
        respuestas.append(
            "Te comento que la fecha indicada ya fue verificada y no se encuentra disponible en este momento. "
            "Por favor, indícanos otra fecha para poder ayudarte."
        )
        msg_log = "La fecha solicitada ya está marcada como NO_DISPONIBLE en la sesión."
    # 2. Hay fecha válida (proporcionada en mensaje actual o guardada)
    elif msg_fecha != "VACIO" and msg_fecha:
        # Consultamos el Google Calendar para esa fecha (00:00:00 a 23:59:59)
        inicio = f"{msg_fecha}T00:00:00Z"
        fin = f"{msg_fecha}T23:59:59Z"
        
        esta_disponible = await servicio_calendario.verificar_disponibilidad(inicio, fin)
        
        # Formatear la fecha en formato dd/mm/yyyy para la respuesta al usuario
        try:
            fecha_formateada = datetime.strptime(msg_fecha, "%Y-%m-%d").strftime("%d/%m/%Y")
        except Exception:
            fecha_formateada = msg_fecha

        if esta_disponible:
            respuestas.append(f"¡Excelente noticia! La fecha {fecha_formateada} está disponible para tu evento.")
            await actualizar_disponibilidad_sesion(phone_number, "DISPONIBLE")
            slots["Sesion_Disponibilidad_Fecha"] = "DISPONIBLE"
            msg_log = f"Consulta a Google Calendar para {msg_fecha}: DISPONIBLE. Se actualizó sesión."
        else:
            respuestas.append(
                f"Lo sentimos, la fecha {fecha_formateada} ya se encuentra reservada u ocupada. "
                "¿Tienes alguna fecha alternativa en mente?"
            )
            await actualizar_disponibilidad_sesion(phone_number, "VACIO")
            await actualizar_fecha_sesion(phone_number, "VACIO")
            slots["Sesion_Disponibilidad_Fecha"] = "VACIO"
            slots["Sesion_FechaISO"] = "VACIO"
            msg_log = f"Consulta a Google Calendar para {msg_fecha}: RESERVADA (NO DISPONIBLE). Se actualizó sesión y se limpió el slot de fecha y disponibilidad."
            # Si no está disponible, cancelamos precios o información irrelevante
            if "PRECIOS" in categorias:
                categorias.remove("PRECIOS")
                msg_log += " Se removió categoría PRECIOS de la cola."
    # 3. No hay fecha (Slot Filling)
    else:
        respuestas.append("Para poder brindarte información de disponibilidad, indícame la fecha de tu evento en formato dd/mm/aaaa.")
        terminar = True
        msg_log = "No se detectó fecha en el mensaje ni en la sesión. Solicitando fecha al usuario (Slot Filling)."

    if "DISPONIBILIDAD" in categorias:
        categorias.remove("DISPONIBILIDAD")

    logs.append({
        "paso": "disponibilidad",
        "mensaje": f"Nodo de Disponibilidad ejecutado.\n- Fecha mensaje: {msg_fecha}\n- Fecha sesión: {fecha_sesion}\n- Detalle: {msg_log}",
        "detalles_tecnicos": {
            "google_calendar_call": f"verificar_disponibilidad(inicio='{msg_fecha}T00:00:00Z', fin='{msg_fecha}T23:59:59Z')" if msg_fecha != "VACIO" and msg_fecha else "No ejecutado",
            "resultado": "esta_disponible = " + str(esta_disponible) if 'esta_disponible' in locals() else "No consultado (fecha ausente o ya verificada)"
        }
    })

    return {
        "categorias_pendientes": categorias,
        "respuestas": respuestas,
        "sesion_slots": slots,
        "terminar_inmediatamente": terminar,
        "logs_ejecucion": logs
    }

async def nodo_precios(state: EstadoAgente) -> Dict[str, Any]:
    """Valida los slots (Fecha, Ambiente, Invitados) y calcula el precio usando la función SQL."""
    categorias = list(state["categorias_pendientes"])
    respuestas = list(state["respuestas"])
    slots = state["sesion_slots"]
    logs = list(state.get("logs_ejecucion", []))
    terminar = False

    disponibilidad_sesion = slots.get("Sesion_Disponibilidad_Fecha", "VACIO")
    msg_log = ""

    # 1. Si la fecha ya se marcó como NO disponible, no calculamos precios
    if disponibilidad_sesion == "NO_DISPONIBLE":
        respuestas.append(
            "La fecha indicada no está disponible, por lo que no corresponde calcular un precio. "
            "Si deseas, puedo ayudarte a revisar otras fechas o brindarte información adicional."
        )
        msg_log = "La fecha está reservada (NO_DISPONIBLE), omitiendo cálculo de precio."
    else:
        # Unificar variables desde mensaje y sesión (preferencia a lo que viene en el mensaje)
        fecha = state["msg_FechaISO"] if state["msg_FechaISO"] != "VACIO" else slots.get("Sesion_FechaISO", "VACIO")
        ambiente = state["msg_Ambiente"] if state["msg_Ambiente"] != "VACIO" else slots.get("Sesion_Ambiente", "VACIO")
        invitados = state["msg_Invitados"] if state["msg_Invitados"] != "VACIO" else slots.get("Sesion_Invitados", "VACIO")

        # Mapear nombres a formato usable
        if ambiente == "SALON CERRADO":
            ambiente = "SALON_CERRADO"
        elif ambiente == "AMBIENTE DE JARDIN":
            ambiente = "AMBIENTE_JARDIN"
        elif ambiente == "AMBOS AMBIENTES":
            ambiente = "AMBOS_AMBIENTES"

        # Si no hay ambiente pero sí hay invitados, podemos sugerir o asignar según la capacidad
        if (ambiente == "VACIO" or not ambiente) and (invitados != "VACIO" and invitados):
            try:
                num_invitados = int(invitados)
                if num_invitados > 300:
                    # El único ambiente que soporta > 300 es AMBOS_AMBIENTES (hasta 450)
                    ambiente = "AMBOS_AMBIENTES"
                    from tools.db_tools import actualizar_ambiente_sesion
                    await actualizar_ambiente_sesion(phone_number, "AMBOS_AMBIENTES")
                    msg_log = f"Ambiente auto-asignado: AMBOS_AMBIENTES (invitados: {num_invitados} > 300)"
            except ValueError:
                pass

        # 2. Validar que tengamos todos los datos necesarios (Slot filling inteligente)
        if fecha == "VACIO" or not fecha:
            respuestas.append("Para poder avanzar, indícame la fecha del evento en formato dd/mm/aaaa.")
            terminar = True
            msg_log = "Falta slot: Fecha. Solicitando fecha."
        elif ambiente == "VACIO" or not ambiente:
            try:
                num_invitados_env = int(invitados) if (invitados != "VACIO" and invitados) else 0
            except ValueError:
                num_invitados_env = 0

            if num_invitados_env > 150:
                respuestas.append(
                    f"Para un evento de {num_invitados_env} invitados, el salón cerrado (capacidad máxima 150) no es suficiente. "
                    "Disponemos de las siguientes opciones:\n"
                    "• Ambiente del jardín (hasta 300 invitados)\n"
                    "• Ambos ambientes (hasta 450 invitados)\n"
                    "¿Cuál de estas opciones prefieres?"
                )
            else:
                respuestas.append(
                    "¿En qué ambiente deseas realizar tu evento? Las opciones son:\n"
                    "• Salón cerrado\n"
                    "• Ambiente del jardín\n"
                    "• Ambos ambientes"
                )
            terminar = True
            msg_log = "Falta slot: Ambiente. Solicitando ambiente adaptado a la capacidad."
        elif invitados == "VACIO" or not invitados:
            respuestas.append("Perfecto. ¿Cuántos invitados serían en total para tu evento?")
            terminar = True
            msg_log = "Falta slot: Invitados. Solicitando cantidad de invitados."
        # 3. Si tenemos todo, llamamos a la base de datos para calcular el precio
        else:
            try:
                num_invitados = int(invitados)
                precio = await obtener_precio_evento(fecha, ambiente, num_invitados)
                
                if precio is not None:
                    # Formatear la fecha en formato dd/mm/yyyy para la respuesta de precios
                    try:
                        fecha_formateada_precios = datetime.strptime(fecha, "%Y-%m-%d").strftime("%d/%m/%Y")
                    except Exception:
                        fecha_formateada_precios = fecha
                    # Formato obligatorio: S/. X,XXX sin decimales
                    precio_formateado = f"S/. {precio:,.0f}".replace(",", ".") # Formato Perú/Español decimal
                    respuestas.append(
                        f"El precio referencial para tu evento el {fecha_formateada_precios} en {ambiente.replace('_', ' ').lower()} "
                        f"para {num_invitados} invitados es de {precio_formateado}."
                    )
                    msg_log = f"Llamada a fnObtienePrecio({fecha}, {ambiente}, {num_invitados}) exitosa. Precio devuelto: {precio_formateado}"
                else:
                    respuestas.append("No logramos calcular el precio para los parámetros ingresados. Por favor verifica los datos.")
                    msg_log = f"Llamada a fnObtienePrecio({fecha}, {ambiente}, {num_invitados}) retornó None."
            except ValueError:
                respuestas.append("Hubo un problema procesando la cantidad de invitados. Por favor ingresa un número entero.")
                terminar = True
                msg_log = f"Cantidad de invitados inválida: {invitados}."

    if "PRECIOS" in categorias:
        categorias.remove("PRECIOS")

    logs.append({
        "paso": "precios",
        "mensaje": f"Nodo de Precios ejecutado.\n- Slots unificados: Fecha={fecha}, Ambiente={ambiente}, Invitados={invitados}\n- Detalle: {msg_log}",
        "detalles_tecnicos": {
            "funcion_sql": f"obtener_precio_evento(fecha='{fecha}', ambiente='{ambiente}', num_invitados={invitados})" if (fecha != "VACIO" and ambiente != "VACIO" and invitados != "VACIO") else "No ejecutado (slots incompletos)",
            "resultado": f"precio = S/. {precio}" if 'precio' in locals() and precio is not None else "No retornado / error"
        }
    })

    return {
        "categorias_pendientes": categorias,
        "respuestas": respuestas,
        "terminar_inmediatamente": terminar,
        "logs_ejecucion": logs
    }

import os

PROMPT_FILE_PATH = os.path.join(os.path.dirname(__file__), "prompt_rag.txt")

def obtener_prompt_rag() -> str:
    default_prompt = (
        "Eres Teffy, la asistente virtual de 'Rincón de la Campiña'.\n"
        "Responde a la consulta del usuario de forma amable, clara y muy breve (máximo 250 caracteres), "
        "utilizando únicamente la información provista en el contexto.\n"
        "No inventes datos. Si la información no está en el contexto, di amablemente que no posees esa información.\n\n"
        "Contexto:\n{contexto}\n\n"
        "Consulta del usuario:\n{consulta}\n\n"
        "Respuesta de Teffy:"
    )
    if os.path.exists(PROMPT_FILE_PATH):
        try:
            with open(PROMPT_FILE_PATH, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    return content
        except Exception as e:
            logger.error(f"Error al leer prompt_rag.txt: {e}")
    return default_prompt

async def nodo_informacion(state: EstadoAgente) -> Dict[str, Any]:
    """Llama a la herramienta RAG sobre PGVector y sintetiza la respuesta con GPT-4o-mini."""
    categorias = list(state["categorias_pendientes"])
    respuestas = list(state["respuestas"])
    msg_consulta = state["msg_Consulta"]
    logs = list(state.get("logs_ejecucion", []))

    # 1. Recuperar contexto semántico del RAG
    contexto = await buscador_rag.buscar_informacion(msg_consulta, top_k=12)

    # 2. Utilizar el LLM para redactar una respuesta profesional y sintetizada según el contexto
    prompt_rag_template = obtener_prompt_rag()
    
    # Asegurar que los placeholders existan para no romper .format()
    if "{contexto}" not in prompt_rag_template:
        prompt_rag_template += "\n\nContexto:\n{contexto}"
    if "{consulta}" not in prompt_rag_template:
        prompt_rag_template += "\n\nConsulta del usuario:\n{consulta}\n\nRespuesta:"

    info_respuesta = ""
    try:
        respuesta_llm = await servicio_openai.cliente.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Eres un asistente de atención al cliente preciso y conciso. No inventas información."},
                {"role": "user", "content": prompt_rag_template.format(contexto=contexto, consulta=msg_consulta)}
            ],
            max_tokens=150,
            temperature=0.2
        )
        info_respuesta = respuesta_llm.choices[0].message.content.strip()
        respuestas.append(info_respuesta)
        log_msg = f"Búsqueda semántica RAG finalizada.\n- Contexto recuperado (primeros 400 caracteres):\n{contexto[:400]}...\n\n- Respuesta generada por GPT-4o-mini:\n'{info_respuesta}'"
    except Exception as e:
        logger.error(f"Error al generar respuesta RAG con LLM: {e}")
        info_respuesta = "El local ofrece diversos ambientes para eventos corporativos y sociales. ¿Qué información específica necesitas?"
        respuestas.append(info_respuesta)
        log_msg = f"Error al generar respuesta RAG: {e}.\n- Contexto RAG recuperado:\n{contexto[:400]}...\n\n- Usando fallback estático:\n'{info_respuesta}'"

    if "INFORMACION" in categorias:
        categorias.remove("INFORMACION")

    logs.append({
        "paso": "informacion",
        "mensaje": f"Nodo de Información / RAG ejecutado para la consulta: '{msg_consulta}'\n\n{log_msg}",
        "detalles_tecnicos": {
            "vector_search_top_k": 12,
            "contexto_recuperado": contexto[:1000] + "..." if len(contexto) > 1000 else contexto,
            "prompt_rag_completo": prompt_rag_template.format(contexto=contexto, consulta=msg_consulta) if 'prompt_rag_template' in locals() else "No se pudo formatear"
        }
    })

    return {
        "categorias_pendientes": categorias,
        "respuestas": respuestas,
        "logs_ejecucion": logs
    }

async def nodo_sin_categoria(state: EstadoAgente) -> Dict[str, Any]:
    """Maneja los mensajes sin intención clara y el traspaso a agentes humanos."""
    categorias = list(state["categorias_pendientes"])
    respuestas = list(state["respuestas"])
    logs = list(state.get("logs_ejecucion", []))
    
    # Usar el valor actual inyectado desde la BD
    sin_categoria_count = state["msg_Sin_Categoria"]

    respuesta = (
        "Disculpa, no logré entender tu consulta. ¿Podrías reformularla o darme más detalles? "
        "Puedo ayudarte con precios, disponibilidad o información del local."
    )
    
    # Agregar aviso de asesor humano si es mayor que 2
    if sin_categoria_count > 2:
        respuesta += " Si desea comunicarse con un Asesor Humano, escriba solo ASESOR."

    respuestas.append(respuesta)

    if "SIN_CATEGORIA" in categorias:
        categorias.remove("SIN_CATEGORIA")

    logs.append({
        "paso": "sin_categoria",
        "mensaje": f"Nodo Sin Categoría ejecutado.\n- Contador de fallos consecutivos: {sin_categoria_count}\n- Respuesta enviada: '{respuesta}'"
    })

    return {
        "categorias_pendientes": categorias,
        "respuestas": respuestas,
        "logs_ejecucion": logs
    }

async def nodo_compilar(state: EstadoAgente) -> Dict[str, Any]:
    """Une las respuestas parciales y formatea el mensaje final (max 400 caracteres)."""
    respuestas = state["respuestas"]
    phone_number = state["phone_number"]
    logs = list(state.get("logs_ejecucion", []))
    
    # 1. Unificar las respuestas generadas
    texto_final = "\n\n".join(respuestas).strip()
    
    # 2. Regla estricta: Máximo 400 caracteres
    # Si excede, usamos el LLM para resumir y formatear de manera elegante respetando el límite
    log_resumen = "Respuesta consolidada dentro del límite de 400 caracteres."
    if len(texto_final) > 400:
        logger.info(f"La respuesta consolidada excede 400 caracteres ({len(texto_final)}). Resumiendo...")
        prompt_resumen = (
            "Consolida y resume el siguiente mensaje para que tenga como máximo 380 caracteres, "
            "manteniendo la amabilidad y respondiendo puntualmente a las consultas del cliente. "
            "No omitas información de precios o fechas si ya están presentes:\n\n"
            f"{texto_final}"
        )
        try:
            respuesta_resumen = await servicio_openai.cliente.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Eres Teffy del Rincón de la Campiña. Resumes mensajes de chat de forma profesional y corta."},
                    {"role": "user", "content": prompt_resumen}
                ],
                max_tokens=150,
                temperature=0.3
            )
            texto_resumido = respuesta_resumen.choices[0].message.content.strip()
            log_resumen = f"Resumen exitoso con GPT-4o-mini de {len(texto_final)} a {len(texto_resumido)} caracteres."
            texto_final = texto_resumido
        except Exception as e:
            logger.error(f"Error al resumir respuesta excedida: {e}")
            texto_final = texto_final[:397] + "..."
            log_resumen = f"Error al resumir con LLM ({e}), recortando por fuerza bruta."

    logger.info(f"Respuesta final compilada: '{texto_final}'")

    # 3. Guardar en el historial de chat (n8n_chat_histories)
    await guardar_mensaje_historial(phone_number, json.dumps({"role": "user", "message": state["msg_Consulta"]}))
    await guardar_mensaje_historial(phone_number, json.dumps({"role": "assistant", "message": texto_final}))

    logs.append({
        "paso": "compile",
        "mensaje": f"Nodo de Compilación finalizado.\n- Estado del Resumen: {log_resumen}\n- Respuesta consolidada final:\n'{texto_final}'"
    })

    # Retorna la respuesta final y el log acumulado para que la API de WhatsApp o la traza pueda enviarla
    return {
        "respuestas": [texto_final],
        "logs_ejecucion": logs
    }

# ------------------------------------------------------------
# CONSTRUCCIÓN DEL GRAFO DE ESTADOS DETERMINISTA
# ------------------------------------------------------------

def enrutador_categorias(state: EstadoAgente) -> str:
    """Función de enrutamiento basada en las intenciones pendientes."""
    if state.get("terminar_inmediatamente", False):
        return "compile"
        
    categorias = state.get("categorias_pendientes", [])
    if not categorias:
        return "compile"
        
    # Obtener el siguiente elemento a procesar
    siguiente = categorias[0]
    
    if siguiente == "SALUDO":
        return "saludo"
    elif siguiente == "DISPONIBILIDAD":
        return "disponibilidad"
    elif siguiente == "PRECIOS":
        return "precios"
    elif siguiente == "INFORMACION":
        return "informacion"
    elif siguiente == "SIN_CATEGORIA":
        return "sin_categoria"
    
    return "compile"

# Inicializar constructor de grafos
workflow = StateGraph(EstadoAgente)

# Registrar nodos
workflow.add_node("init", nodo_inicializar)
workflow.add_node("saludo", nodo_saludo)
workflow.add_node("disponibilidad", nodo_disponibilidad)
workflow.add_node("precios", nodo_precios)
workflow.add_node("informacion", nodo_informacion)
workflow.add_node("sin_categoria", nodo_sin_categoria)
workflow.add_node("compile", nodo_compilar)

# Configurar entrada
workflow.set_entry_point("init")

# Configurar transiciones condicionales de enrutamiento
workflow.add_conditional_edges(
    "init",
    enrutador_categorias,
    {
        "saludo": "saludo",
        "disponibilidad": "disponibilidad",
        "precios": "precios",
        "informacion": "informacion",
        "sin_categoria": "sin_categoria",
        "compile": "compile"
    }
)

# Configurar retornos desde nodos al enrutador central
workflow.add_conditional_edges("saludo", enrutador_categorias, {"saludo": "saludo", "disponibilidad": "disponibilidad", "precios": "precios", "informacion": "informacion", "sin_categoria": "sin_categoria", "compile": "compile"})
workflow.add_conditional_edges("disponibilidad", enrutador_categorias, {"saludo": "saludo", "disponibilidad": "disponibilidad", "precios": "precios", "informacion": "informacion", "sin_categoria": "sin_categoria", "compile": "compile"})
workflow.add_conditional_edges("precios", enrutador_categorias, {"saludo": "saludo", "disponibilidad": "disponibilidad", "precios": "precios", "informacion": "informacion", "sin_categoria": "sin_categoria", "compile": "compile"})
workflow.add_conditional_edges("informacion", enrutador_categorias, {"saludo": "saludo", "disponibilidad": "disponibilidad", "precios": "precios", "informacion": "informacion", "sin_categoria": "sin_categoria", "compile": "compile"})
workflow.add_conditional_edges("sin_categoria", enrutador_categorias, {"saludo": "saludo", "disponibilidad": "disponibilidad", "precios": "precios", "informacion": "informacion", "sin_categoria": "sin_categoria", "compile": "compile"})

# El nodo compile conecta al fin del grafo
workflow.add_edge("compile", END)

# Compilar grafo
agente_langgraph = workflow.compile()
