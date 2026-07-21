import json
import logging
from typing import List, Dict, Any, TypedDict, Annotated, Optional
from langgraph.graph import StateGraph, END
from config import configuracion
from services.openai_service import servicio_openai
from tools.db_tools import (
    obtener_estado_sesion,
    contar_mensajes_historial,
    obtener_precio_evento,
    actualizar_disponibilidad_sesion,
    actualizar_fecha_sesion,
    actualizar_ambiente_sesion,
    actualizar_invitados_sesion,
    guardar_mensaje_historial,
    bot_se_presento,
    obtener_historial_chat
)
from tools.calendar import servicio_calendario
from tools.rag import buscador_rag
from datetime import datetime

logger = logging.getLogger(__name__)

# Definición del Estado del Agente conforme a los requerimientos originales
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
    
    sesion_slots: Dict[str, Any]
    categorias_pendientes: List[str]
    respuestas: List[str]
    terminar_inmediatamente: bool
    logs_ejecucion: List[Dict[str, Any]]
    
    # Campo extra para el historial de mensajes de la API de OpenAI
    llm_messages: List[Dict[str, Any]]
    llm_model: str

# ------------------------------------------------------------
# HERRAMIENTAS (TOOLS) PARA EL LLM
# ------------------------------------------------------------

async def tool_verificar_disponibilidad(phone_number: str, fecha_iso: str) -> str:
    """Verifica si una fecha en formato YYYY-MM-DD está disponible en el calendario."""
    inicio = f"{fecha_iso}T00:00:00Z"
    fin = f"{fecha_iso}T23:59:59Z"
    esta_disponible = await servicio_calendario.verificar_disponibilidad(inicio, fin)
    if esta_disponible:
        await actualizar_disponibilidad_sesion(phone_number, "DISPONIBLE")
        return "DISPONIBLE"
    else:
        await actualizar_disponibilidad_sesion(phone_number, "VACIO")
        await actualizar_fecha_sesion(phone_number, "VACIO")
        return "NO_DISPONIBLE"

async def tool_calcular_precio(fecha_iso: str, ambiente: str, invitados: int) -> str:
    """Calcula el precio de un evento dado la fecha, el ambiente (SALON_CERRADO, AMBIENTE_JARDIN, AMBOS_AMBIENTES) y la cantidad de invitados."""
    precio = await obtener_precio_evento(fecha_iso, ambiente, invitados)
    if precio is not None:
        return f"Precio calculado: S/. {precio:,.0f}".replace(",", ".")
    return "No se pudo calcular el precio con los parámetros indicados."

async def tool_buscar_informacion(consulta: str) -> str:
    """Busca información general sobre el local, capacidades de ambientes, servicios, etc. en la base de datos de conocimiento (RAG)."""
    contexto = await buscador_rag.buscar_informacion(consulta, top_k=12)
    
    prompt_rag_template = await obtener_prompt_rag()
    if "{contexto}" not in prompt_rag_template:
        prompt_rag_template += "\n\nContexto:\n{contexto}"
    if "{consulta}" not in prompt_rag_template:
        prompt_rag_template += "\n\nConsulta del usuario:\n{consulta}\n\nRespuesta:"
        
    try:
        respuesta_llm = await servicio_openai.cliente.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Eres un asistente de atención al cliente preciso y conciso. No inventas información."},
                {"role": "user", "content": prompt_rag_template.format(contexto=contexto, consulta=consulta)}
            ],
            max_tokens=500,
            temperature=0.2
        )
        return respuesta_llm.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"Error al generar respuesta RAG con LLM: {e}")
        return f"Información encontrada:\n{contexto}"

async def tool_actualizar_slots_sesion(phone_number: str, fecha_iso: Optional[str] = None, ambiente: Optional[str] = None, invitados: Optional[int] = None) -> str:
    """Actualiza la información de la sesión actual del usuario en la base de datos."""
    cambios = []
    if fecha_iso and fecha_iso != "VACIO":
        await actualizar_fecha_sesion(phone_number, fecha_iso)
        cambios.append(f"fecha={fecha_iso}")
    if ambiente and ambiente != "VACIO":
        await actualizar_ambiente_sesion(phone_number, ambiente)
        cambios.append(f"ambiente={ambiente}")
    if invitados and invitados != "VACIO":
        try:
            await actualizar_invitados_sesion(phone_number, int(invitados))
            cambios.append(f"invitados={invitados}")
        except Exception:
            pass
    if cambios:
        return "Slots actualizados: " + ", ".join(cambios)
    return "No hubo slots válidos para actualizar."

async def tool_obtener_multimedia_ambiente(ambiente: str, tipo: str, modo: str = "primeros_3") -> str:
    """Obtiene enlaces a fotos o videos del ambiente seleccionado (SALON_CERRADO, AMBIENTE_JARDIN o COMUNES) para mostrárselas al cliente. tipo debe ser 'fotos' o 'videos'. modo puede ser 'primeros_3' o 'resto'."""
    import os
    import re
    folder_map = {
        "SALON_CERRADO": "salon",
        "AMBIENTE_JARDIN": "jardin",
        "COMUNES": "comunes"
    }
    subfolder = folder_map.get(ambiente, "jardin")
    base_path = f"./media/{subfolder}"
    if not os.path.exists(base_path):
        return f"No hay {tipo} disponibles para el ambiente o área {ambiente} en este momento."
        
    try:
        archivos = [f for f in os.listdir(base_path) if os.path.isfile(os.path.join(base_path, f))]
    except Exception:
        return f"Error al acceder a los archivos de {tipo}."

    imagenes_ext = ('.png', '.jpg', '.jpeg', '.webp')
    videos_ext = ('.mp4', '.mov', '.avi')
    
    # Filtrar solo archivos con extensiones correctas que comiencen con un dígito + _
    if tipo == "fotos":
        archivos = [a for a in archivos if a.lower().endswith(imagenes_ext) and re.match(r'^\d+_', a)]
    elif tipo == "videos":
        archivos = [a for a in archivos if a.lower().endswith(videos_ext) and re.match(r'^\d+_', a)]
        
    # Ordenar alfabéticamente para asegurar consistencia
    archivos = sorted(archivos)

    if not archivos:
        return f"No se encontraron {tipo} oficiales (que comiencen con un número) para el ambiente/área {ambiente}."
        
    # Determinar qué parte del array enviar según el modo
    if modo == "primeros_3":
        seleccionados = archivos[:3]
        titulo = f"Aquí tienes las primeras {tipo} de {ambiente}:"
    else:
        seleccionados = archivos[3:]
        titulo = f"Aquí tienes el resto de {tipo} de {ambiente}:"
        
    if not seleccionados:
        return f"No hay más {tipo} disponibles en este momento para {ambiente}."

    enlaces = []
    for a in seleccionados:
        url = f"/api/media/{subfolder}/{a}"
        if tipo == "fotos":
            enlaces.append(f"![{a}]({url})")
        else:
            enlaces.append(f"[Video de muestra: {a}]({url})")
            
    return f"{titulo}\n" + "\n".join(enlaces)

# Diccionario de funciones para el dispatch
TOOLS_FUNCTIONS = {
    "verificar_disponibilidad": tool_verificar_disponibilidad,
    "calcular_precio": tool_calcular_precio,
    "buscar_informacion": tool_buscar_informacion,
    "actualizar_slots_sesion": tool_actualizar_slots_sesion,
    "obtener_multimedia_ambiente": tool_obtener_multimedia_ambiente
}

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "verificar_disponibilidad",
            "description": "Verifica si una fecha en formato YYYY-MM-DD está disponible en el calendario.",
            "parameters": {
                "type": "object",
                "properties": {
                    "phone_number": {"type": "string", "description": "El número de teléfono del usuario actual."},
                    "fecha_iso": {"type": "string", "description": "Fecha a consultar en formato YYYY-MM-DD."}
                },
                "required": ["phone_number", "fecha_iso"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calcular_precio",
            "description": "Calcula el precio para el evento.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fecha_iso": {"type": "string", "description": "Fecha del evento en YYYY-MM-DD."},
                    "ambiente": {"type": "string", "enum": ["SALON_CERRADO", "AMBIENTE_JARDIN", "AMBOS_AMBIENTES"], "description": "Ambiente deseado."},
                    "invitados": {"type": "integer", "description": "Cantidad de invitados."}
                },
                "required": ["fecha_iso", "ambiente", "invitados"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "buscar_informacion",
            "description": "Busca información de conocimiento general sobre el local (capacidades, servicios extra, qué incluye).",
            "parameters": {
                "type": "object",
                "properties": {
                    "consulta": {"type": "string", "description": "Pregunta detallada para buscar en la base de conocimientos."}
                },
                "required": ["consulta"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "actualizar_slots_sesion",
            "description": "Actualiza la base de datos de la sesión con los datos que el usuario acaba de proveer (fecha, ambiente, invitados).",
            "parameters": {
                "type": "object",
                "properties": {
                    "phone_number": {"type": "string", "description": "El número de teléfono del usuario actual."},
                    "fecha_iso": {"type": "string", "description": "YYYY-MM-DD si se proveyó."},
                    "ambiente": {"type": "string", "description": "SALON_CERRADO, AMBIENTE_JARDIN o AMBOS_AMBIENTES."},
                    "invitados": {"type": "integer", "description": "Número de invitados."}
                },
                "required": ["phone_number"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "obtener_multimedia_ambiente",
            "description": "Obtiene enlaces de fotos o videos para un ambiente ('SALON_CERRADO', 'AMBIENTE_JARDIN' o 'COMUNES'). CRITICAL: Debes copiar los enlaces markdown retornados EXACTAMENTE como se proveen en la respuesta final, sin alterar las rutas ni modificar las extensiones (.jpeg/.png).",
            "parameters": {
                "type": "object",
                "properties": {
                    "ambiente": {"type": "string", "enum": ["SALON_CERRADO", "AMBIENTE_JARDIN", "COMUNES"], "description": "Ambiente o área a mostrar."},
                    "tipo": {"type": "string", "enum": ["fotos", "videos"], "description": "Tipo de archivo multimedia ('fotos' o 'videos')."},
                    "modo": {"type": "string", "enum": ["primeros_3", "resto"], "description": "Si es 'primeros_3' para la primera consulta de fotos, o 'resto' si el usuario pide ver más archivos o el resto del contenido."}
                },
                "required": ["ambiente", "tipo"]
            }
        }
    }
]

# ------------------------------------------------------------
# NODOS DEL GRAFO
# ------------------------------------------------------------

async def nodo_inicializar(state: EstadoAgente) -> Dict[str, Any]:
    """Carga estado de sesión, historial y define el prompt del sistema."""
    phone_number = state["phone_number"]
    
    slots = await obtener_estado_sesion(phone_number)
    msg_count = await contar_mensajes_historial(phone_number)
    presento = await bot_se_presento(phone_number)

    # Reconciliar slots de entrada con los de sesión para que el LLM los actualice si es necesario
    fecha = state.get("msg_FechaISO", "VACIO")
    ambiente = state.get("msg_Ambiente", "VACIO")
    invitados = state.get("msg_Invitados", "VACIO")
    
    if fecha != "VACIO" or ambiente != "VACIO" or invitados != "VACIO":
        await tool_actualizar_slots_sesion(phone_number, fecha, ambiente, invitados)
        # Recargamos para tener lo más fresco
        slots = await obtener_estado_sesion(phone_number)

    # Prompt del sistema desde base de datos
    system_prompt_template = await obtener_system_prompt()
    
    presentacion_str = "" if presento else "Preséntate en el primer mensaje.\n"
    system_prompt = system_prompt_template.format(
        presentacion=presentacion_str,
        phone_number=phone_number,
        slots_invitados=slots.get('Sesion_Invitados', 'VACIO'),
        slots_fecha=slots.get('Sesion_FechaISO', 'VACIO'),
        slots_ambiente=slots.get('Sesion_Ambiente', 'VACIO'),
        slots_disponibilidad=slots.get('Sesion_Disponibilidad_Fecha', 'VACIO')
    )

    llm_messages = [{"role": "system", "content": system_prompt}]
    
    # Cargar historial de chat previo para dar memoria contextual al LLM
    historial_previo = await obtener_historial_chat(phone_number, limit=10)
    llm_messages.extend(historial_previo)
    
    # Agregar la consulta actual del usuario
    consulta_usuario = state["msg_Consulta"]
    llm_messages.append({"role": "user", "content": consulta_usuario})

    logs = [{
        "paso": "init",
        "mensaje": f"Agente inicializado. Slots: {slots}"
    }]

    return {
        "sesion_slots": slots,
        "message_count": msg_count,
        "llm_messages": llm_messages,
        "respuestas": [],
        "logs_ejecucion": logs
    }

async def nodo_agente(state: EstadoAgente) -> Dict[str, Any]:
    """Invoca al LLM (GPT-4o-mini). Si el LLM pide herramientas, se enrutan. Si responde, terminamos."""
    llm_messages = state.get("llm_messages", [])
    logs = list(state.get("logs_ejecucion", []))
    respuestas = list(state.get("respuestas", []))
    
    try:
        modelo_seleccionado = state.get("llm_model", "gpt-4o-mini")
        respuesta_llm = await servicio_openai.cliente.chat.completions.create(
            model=modelo_seleccionado,
            messages=llm_messages,
            tools=TOOLS_SCHEMA,
            tool_choice="auto",
            temperature=0.2,
            max_tokens=1000
        )
        
        mensaje_respuesta = respuesta_llm.choices[0].message
        
        # Guardamos la respuesta del asistente en el historial
        llm_messages.append(mensaje_respuesta)
        
        if mensaje_respuesta.tool_calls:
            logs.append({"paso": "agente_tools", "mensaje": f"LLM solicitó herramientas: {len(mensaje_respuesta.tool_calls)}"})
        else:
            texto_final = mensaje_respuesta.content.strip()
            respuestas.append(texto_final)
            logs.append({"paso": "agente_respuesta", "mensaje": "LLM generó respuesta final."})
            
    except Exception as e:
        logger.error(f"Error en el LLM del Agente: {e}")
        respuestas.append("Disculpa, tuve un problema procesando tu consulta. ¿Podrías repetirla?")
        logs.append({"paso": "agente_error", "mensaje": str(e)})

    return {
        "llm_messages": llm_messages,
        "respuestas": respuestas,
        "logs_ejecucion": logs
    }

async def nodo_herramientas(state: EstadoAgente) -> Dict[str, Any]:
    """Ejecuta las herramientas solicitadas por el LLM y devuelve el resultado."""
    llm_messages = state["llm_messages"]
    logs = list(state.get("logs_ejecucion", []))
    phone_number = state["phone_number"]
    
    # El último mensaje debería ser el del asistente con tool_calls
    ultimo_mensaje = llm_messages[-1]
    
    if not hasattr(ultimo_mensaje, "tool_calls") or not ultimo_mensaje.tool_calls:
        return {}

    for tool_call in ultimo_mensaje.tool_calls:
        func_name = tool_call.function.name
        args_str = tool_call.function.arguments
        
        logs.append({"paso": "herramienta_ejecucion", "mensaje": f"Ejecutando {func_name} con args: {args_str}"})
        
        resultado = "Error interno ejecutando herramienta."
        try:
            import json
            kwargs = json.loads(args_str)
            if func_name == "actualizar_slots_sesion":
                kwargs["phone_number"] = phone_number
                
            if func_name in TOOLS_FUNCTIONS:
                resultado = await TOOLS_FUNCTIONS[func_name](**kwargs)
            else:
                resultado = f"Herramienta {func_name} no existe."
        except Exception as e:
            logger.error(f"Error ejecutando herramienta {func_name}: {e}")
            resultado = f"Fallo en {func_name}: {e}"
            
        # Añadir el resultado al historial como rol tool
        llm_messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "name": func_name,
            "content": str(resultado)
        })
        
    return {
        "llm_messages": llm_messages,
        "logs_ejecucion": logs
    }

async def nodo_compilar(state: EstadoAgente) -> Dict[str, Any]:
    """Guarda en BD el historial y consolida la salida final."""
    respuestas = state["respuestas"]
    phone_number = state["phone_number"]
    logs = list(state.get("logs_ejecucion", []))
    
    texto_final = "\n".join(respuestas).strip()
    if not texto_final:
        texto_final = "Hubo un error de procesamiento. Por favor intenta de nuevo."
        
    # Guardar en el historial de chat (n8n_chat_histories)
    await guardar_mensaje_historial(phone_number, json.dumps({"role": "user", "message": state["msg_Consulta"]}))
    await guardar_mensaje_historial(phone_number, json.dumps({"role": "assistant", "message": texto_final}))

    logs.append({
        "paso": "compile",
        "mensaje": f"Respuesta final enviada: '{texto_final}'"
    })

    return {
        "respuestas": [texto_final],
        "logs_ejecucion": logs
    }

# ------------------------------------------------------------
# CONSTRUCCIÓN DEL GRAFO DE AGENTE (ReAct)
# ------------------------------------------------------------

def enrutador_agente(state: EstadoAgente) -> str:
    """Decide si volver al LLM o terminar."""
    if not state.get("llm_messages"):
        return "compile"
    
    ultimo_mensaje = state["llm_messages"][-1]
    
    # Si el último mensaje es de un asistente y tiene tool_calls, vamos a ejecutar herramientas
    if hasattr(ultimo_mensaje, "tool_calls") and ultimo_mensaje.tool_calls:
        return "herramientas"
    
    # Si no tiene tool calls, significa que dio la respuesta final
    return "compile"

workflow = StateGraph(EstadoAgente)

workflow.add_node("init", nodo_inicializar)
workflow.add_node("agente", nodo_agente)
workflow.add_node("herramientas", nodo_herramientas)
workflow.add_node("compile", nodo_compilar)

workflow.set_entry_point("init")

workflow.add_edge("init", "agente")

# Enrutador condicional: después del agente, vamos a herramientas o compilamos
workflow.add_conditional_edges(
    "agente",
    enrutador_agente,
    {
        "herramientas": "herramientas",
        "compile": "compile"
    }
)

# Después de ejecutar las herramientas, siempre devolvemos el resultado al agente
workflow.add_edge("herramientas", "agente")

workflow.add_edge("compile", END)

agente_langgraph = workflow.compile()

import os
PROMPT_FILE_PATH = os.path.join(os.path.dirname(__file__), "prompt_rag.txt")

async def obtener_prompt_rag() -> str:
    """
    Intenta obtener el prompt de RAG desde la base de datos (public.hv_prompt_config).
    Si falla, lee desde el archivo local prompt_rag.txt o usa el prompt por defecto.
    """
    default_prompt = (
        "Eres Teffy, la asistente virtual de 'Rincón de la Campiña'.\n"
        "Responde a la consulta del usuario de forma amable, clara y muy breve (máximo 250 caracteres), "
        "utilizando únicamente la información provista en el contexto.\n"
        "No inventes datos. Si la información no está en el contexto, di amablemente que no posees esa información.\n\n"
        "Contexto:\n{contexto}\n\n"
        "Consulta del usuario:\n{consulta}\n\n"
        "Respuesta de Teffy:"
    )
    
    # 1. Intentar consultar base de datos
    try:
        from core.database import obtener_sesion_hv
        from sqlalchemy import text
        async with obtener_sesion_hv() as sesion:
            res = await sesion.execute(text("SELECT valor FROM public.hv_prompt_config WHERE clave = 'prompt_rag'"))
            fila = res.fetchone()
            if fila and fila[0]:
                return fila[0].strip()
    except Exception as e:
        logger.error(f"Error al consultar prompt en BD: {e}")

    # 2. Fallback a archivo local o constante
    if os.path.exists(PROMPT_FILE_PATH):
        try:
            with open(PROMPT_FILE_PATH, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    return content
        except Exception as e:
            logger.error(f"Error al leer prompt_rag.txt: {e}")
    return default_prompt


async def obtener_system_prompt() -> str:
    """
    Intenta obtener el system prompt del agente desde la base de datos (public.hv_prompt_config).
    Si falla, devuelve la plantilla por defecto.
    """
    default_prompt_template = (
        "Eres Teffy, la asistente virtual del local de eventos 'Rincón de la Campiña'.\n"
        "Tu objetivo es conversar con los usuarios, responder amablemente y recopilar la información necesaria para brindarles un precio.\n"
        "Reglas:\n"
        "1. Eres cordial. {presentacion}\n"
        "2. **CÁLIDA, ENTUSIASTA Y HUMANA (MÁXIMA PRIORIDAD)**: Si el usuario menciona que va a celebrar un evento (ej. 'me caso', 'mi boda', 'mi cumpleaños', 'un quinceañero', etc. - incluso si los menciona juntos o bromea), FELICÍTALO efusivamente al inicio de tu respuesta de forma obligatoria (ej: '¡Qué gran noticia! 💖 ¡Muchas felicidades por tu boda / quinceañero! 🎉'). Esta felicitación es de obligado cumplimiento y debe ser tu primera oración.\n"
        "3. **CONSULTA DE DISPONIBILIDAD OBLIGATORIA (CALENDAR)**: Si el usuario te proporciona una fecha (en su mensaje o si está guardada en el 'Estado actual de la sesión' pero la disponibilidad de la fecha es 'VACIO'), debes llamar de inmediato a la herramienta `verificar_disponibilidad` para comprobar si la fecha está libre. Es de máxima prioridad verificar la fecha en Google Calendar.\n"
        "4. **GUARDADO OBLIGATORIO DE DATOS (SLOTS)**: Si el usuario menciona nuevos datos de fecha (como '28 de julio' -> deduce '2026-07-28'), cantidad de invitados (como '250') o ambiente, o si estos datos difieren o faltan en el 'Estado actual de la sesión', DEBES llamar de inmediato a la herramienta `actualizar_slots_sesion` para guardarlos. Asimismo, si sugieres o infieres un ambiente específico debido a restricciones de aforo (por ejemplo, si hay 300 invitados y descartas el salón cerrado porque solo entran 180, calculando el Jardín Abierto), DEBES llamar de inmediato a `actualizar_slots_sesion` para guardar ese ambiente en la sesión.\n"
        "5. NUNCA asumas capacidades ni información general. Siempre usa la herramienta 'buscar_informacion' si el cliente pregunta sobre el local o detalles de los ambientes.\n"
        "6. **VALIDACIÓN DE CAPACIDAD DE AMBIENTES (MÁXIMA PRIORIDAD)**: Ten muy presente las capacidades de cada ambiente:\n"
        "   - **Salón Cerrado (`SALON_CERRADO`):** Capacidad máxima de **180 invitados**.\n"
        "   - **Jardín Abierto (`AMBIENTE_JARDIN`):** Capacidad máxima de **300 invitados**.\n"
        "   - **Ambos Ambientes (`AMBOS_AMBIENTES`):** Capacidad máxima de **480 invitados**.\n"
        "   - **Restricciones de guardado:** Si la cantidad de invitados es mayor a 180 (ej. 250), NO propongas el Salón Cerrado ni llames a `actualizar_slots_sesion` con `SALON_CERRADO`. Si el usuario te pide explícitamente el Salón Cerrado pero supera la capacidad, dile amablemente que no es posible por el aforo y sugiérele usar el Jardín Abierto o Ambos Ambientes.\n"
        "7. **ERES PROACTIVA E INDEPENDIENTE**: Si el usuario menciona una fecha o si los slots tienen la información necesaria, llama a las herramientas de disponibilidad o precios de inmediato sin pedir permiso. NUNCA generes mensajes de texto conversacionales ni textos de relleno (como 'voy a validar', 'espera un momento', 'deja que consulte') en el mismo turno en el que solicitas llamadas a herramientas. Si usas herramientas, hazlo en silencio y directamente; el flujo se encargará de ejecutarlas al instante y devolverte los resultados.\n"
        "8. **MULTIMEDIA (FOTOS Y VIDEOS)**: Si el usuario te pide información sobre un ambiente (SALON_CERRADO o AMBIENTE_JARDIN) o áreas comunes (COMUNES), describe el ambiente y llama a la herramienta `obtener_multimedia_ambiente`.\n"
        "   - Al dar información por primera vez, llama a la herramienta con `modo='primeros_3'` (solo enviará las 3 primeras fotos o videos).\n"
        "   - Si el cliente te pide específicamente ver más fotos, más videos o el resto (ej: 'pásame más fotos', 'quiero ver el resto del jardín'), llama a la herramienta con `modo='resto'`.\n"
        "   - **CRITICAL**: Debes copiar los enlaces markdown devueltos por la herramienta `obtener_multimedia_ambiente` EXACTAMENTE en tu respuesta final. NUNCA alteres el nombre del archivo, las rutas ni las extensiones (por ejemplo, nunca cambies `.jpeg` a `.jpg`), ni inventes tus propios nombres o textos alternativos de imagen.\n"
        "9. Responde de forma completa, clara y detallada, sin cortar oraciones a medias.\n"
        "10. **PRECIOS APROXIMADOS**: Al brindarle al usuario el precio calculado por la herramienta, aclara explícitamente que es un **precio aproximado/referencial** y que para obtener una propuesta final formal debe solicitar una cotización formal con un asesor.\n\n"
        "Estado actual de la sesión (recopilado hasta ahora):\n"
        "- Teléfono del Usuario: {phone_number}\n"
        "- Invitados: {slots_invitados}\n"
        "- Fecha: {slots_fecha}\n"
        "- Ambiente: {slots_ambiente}\n"
        "- Disponibilidad de la Fecha: {slots_disponibilidad}\n"
    )
    
    try:
        from core.database import obtener_sesion_hv
        from sqlalchemy import text
        async with obtener_sesion_hv() as sesion:
            res = await sesion.execute(text("SELECT valor FROM public.hv_prompt_config WHERE clave = 'system_prompt'"))
            fila = res.fetchone()
            if fila and fila[0]:
                return fila[0].strip()
    except Exception as e:
        logger.error(f"Error al consultar system_prompt en BD: {e}")
        
    return default_prompt_template
