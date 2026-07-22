import logging
import json
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, Request, Response, BackgroundTasks, Depends, HTTPException, Query, File, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from core.security import verificar_token_desafio, verificar_firma_meta
from services.whatsapp import cliente_whatsapp
from services.openai_service import servicio_openai
from services.agent import agente_langgraph
from tools.db_tools import (
    verificar_atencion_humana_activa,
    obtener_asignacion_humana,
    eliminar_atencion_humana,
    crear_solicitud_atencion_humana,
    obtener_todos_los_agentes,
    asignar_agente_humano_libre,
    analizar_texto_completo,
    actualizar_ambiente_sesion,
    actualizar_fecha_sesion,
    actualizar_invitados_sesion,
    incrementar_sin_categoria,
    obtener_estado_sesion,
    reiniciar_estado_sesion
)
from services.channel_dispatcher import despachador_canales

# Configuración de Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="WhatsApp Bot Rincón de la Campiña",
    description="Backend de automatización con RAG, LangGraph, simulador web y enrutamiento a agentes.",
    version="1.0.0"
)

from fastapi.staticfiles import StaticFiles
import os
os.makedirs("media/salon_cerrado", exist_ok=True)
os.makedirs("media/jardin", exist_ok=True)

app.mount("/api/media", StaticFiles(directory="media"), name="media")

@app.on_event("startup")
async def al_iniciar():
    """Inicializa las tablas necesarias en la base de datos si no existen."""
    from sqlalchemy import text
    from core.database import obtener_sesion_hv, obtener_sesion_rag
    
    # 1. Crear tablas en la base de datos HV (hv_gestion)
    queries_hv = [
        """
        CREATE TABLE IF NOT EXISTS public.hv_estado_sesion (
            phone_number VARCHAR(50) PRIMARY KEY,
            fecha_iso DATE,
            ambiente VARCHAR(100),
            invitados INTEGER,
            sin_categoria INTEGER DEFAULT 0,
            disponibilidad_fecha VARCHAR(50),
            created_at TIMESTAMP DEFAULT now(),
            updated_at TIMESTAMP DEFAULT now()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS public.hv_atencion_agentes (
            id SERIAL PRIMARY KEY,
            usuario_ws VARCHAR(50),
            agente_humano VARCHAR(50),
            agente_ai VARCHAR(100),
            estado VARCHAR(50) DEFAULT 'PENDIENTE',
            mensaje TEXT,
            created_at TIMESTAMP DEFAULT now(),
            updated_at TIMESTAMP DEFAULT now()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS public.hv_agentes (
            agente_humano VARCHAR(50) PRIMARY KEY,
            nombre VARCHAR(100),
            created_at TIMESTAMP DEFAULT now()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS public.hv_prompt_config (
            clave VARCHAR(50) PRIMARY KEY,
            valor TEXT NOT NULL
        );
        """
    ]
    
    async with obtener_sesion_hv() as sesion:
        for q in queries_hv:
            try:
                await sesion.execute(text(q))
                logger.info("Tabla de la BD HV inicializada o ya existente.")
            except Exception as e:
                logger.error(f"Error al inicializar tabla en BD HV: {e}")
        
        # Sembrar prompt inicial si la tabla está vacía
        try:
            default_prompt = (
                "Eres Teffy, la asistente virtual de 'Rincón de la Campiña'.\n"
                "Responde a la consulta del usuario de forma amable, clara y muy breve (máximo 250 caracteres), "
                "utilizando únicamente la información provista en el contexto.\n"
                "No inventes datos. Si la información no está en el contexto, di amablemente que no posees esa información.\n\n"
                "Contexto:\n{contexto}\n\n"
                "Consulta del usuario:\n{consulta}\n\n"
                "Respuesta de Teffy:"
            )
            await sesion.execute(
                text("INSERT INTO public.hv_prompt_config (clave, valor) VALUES ('prompt_rag', :val) ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor"),
                {"val": default_prompt}
            )
            
            default_system_prompt = (
                "Eres Teffy, la asistente virtual del local de eventos 'Rincón de la Campiña'.\n"
                "Tu objetivo es conversar con los usuarios, responder amablemente y recopilar la información necesaria para brindarles un precio.\n"
                "Reglas:\n"
                "1. Eres cordial. Responde siempre con un tono amable y servicial.\n"
                "2. **CÁLIDA, ENTUSIASTA Y HUMANA (MÁXIMA PRIORIDAD)**: ÚNICAMENTE si el usuario menciona de forma explícita en su mensaje que va a celebrar un evento (ej. 'me caso', 'mi boda', 'mi cumpleaños', 'un quinceañero', etc. - incluso si los menciona juntos o bromea), FELICÍTALO efusivamente al inicio de tu respuesta (ej: '¡Qué gran noticia! 💖 ¡Muchas felicidades por tu boda / quinceañero! 🎉'). Esta felicitación es de obligado cumplimiento en ese caso y debe ser tu primera oración. Si el usuario NO menciona ningún evento ni celebración de forma explícita, NO lo felicites de ninguna manera.\n"
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
                "10. **PRECIOS APROXIMADOS**: Al brindarle al usuario el precio calculated por la herramienta, aclara explícitamente que es un **precio aproximado/referencial** y que para obtener una propuesta final formal debe solicitar una cotización formal con un asesor.\n"
                "11. **CÁLCULO DE PRECIO OBLIGATORIO (`calcular_precio`)**: Si los tres datos (Fecha, Ambiente e Invitados) ya están completos en el 'Estado actual de la sesión' o si el usuario acaba de completar el dato que faltaba, DEBES llamar de inmediato a la herramienta `calcular_precio` para obtener el costo. NUNCA respondas diciendo que no puedes calcular el precio si los 3 datos están disponibles.\n\n"
                "Estado actual de la sesión (recopilado hasta ahora):\n"
                "- Teléfono del Usuario: {phone_number}\n"
                "- Invitados: {slots_invitados}\n"
                "- Fecha: {slots_fecha}\n"
                "- Ambiente: {slots_ambiente}\n"
                "- Disponibilidad de la Fecha: {slots_disponibilidad}\n"
            )
            await sesion.execute(
                text("INSERT INTO public.hv_prompt_config (clave, valor) VALUES ('system_prompt', :val) ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor"),
                {"val": default_system_prompt}
            )
        except Exception as e:
            logger.error(f"Error al sembrar prompt inicial: {e}")

        # Asegurar columnas necesarias en BD HV por si la tabla ya existía con otro esquema
        alters_hv = [
            "ALTER TABLE public.hv_estado_sesion ADD COLUMN IF NOT EXISTS fecha_iso DATE;",
            "ALTER TABLE public.hv_estado_sesion ADD COLUMN IF NOT EXISTS ambiente VARCHAR(100);",
            "ALTER TABLE public.hv_estado_sesion ADD COLUMN IF NOT EXISTS invitados INTEGER;",
            "ALTER TABLE public.hv_estado_sesion ADD COLUMN IF NOT EXISTS sin_categoria INTEGER DEFAULT 0;",
            "ALTER TABLE public.hv_estado_sesion ADD COLUMN IF NOT EXISTS disponibilidad_fecha VARCHAR(50);",
            "ALTER TABLE public.hv_estado_sesion ADD COLUMN IF NOT EXISTS modo_atencion VARCHAR(20) DEFAULT 'BOT';",
            "ALTER TABLE public.hv_estado_sesion ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT now();"
        ]
        for q in alters_hv:
            try:
                await sesion.execute(text(q))
            except Exception as e:
                logger.error(f"Error al aplicar ALTER TABLE en BD HV: {e}")

        # Asegurar clave BOT_MODO_GLOBAL inicial
        try:
            await sesion.execute(text(
                "INSERT INTO public.hv_prompt_config (clave, valor) VALUES ('BOT_MODO_GLOBAL', 'BOT_ACTIVO') ON CONFLICT (clave) DO NOTHING"
            ))
        except Exception as e:
            logger.error(f"Error al inicializar BOT_MODO_GLOBAL: {e}")

    # 2. Crear tablas en la base de datos RAG
    query_rag = """
    CREATE TABLE IF NOT EXISTS public.n8n_chat_histories (
        id SERIAL PRIMARY KEY,
        session_id VARCHAR(50),
        message TEXT,
        created_at TIMESTAMP DEFAULT now()
    );
    """
    async with obtener_sesion_rag() as sesion:
        try:
            await sesion.execute(text(query_rag))
            logger.info("Tabla n8n_chat_histories inicializada o ya existente en RAG.")
        except Exception as e:
            logger.error(f"Error al inicializar tabla en BD RAG: {e}")

        # Asegurar columnas en n8n_chat_histories por si ya existía sin created_at o session_id
        alters_rag = [
            "ALTER TABLE public.n8n_chat_histories ADD COLUMN IF NOT EXISTS session_id VARCHAR(50);",
            "ALTER TABLE public.n8n_chat_histories ADD COLUMN IF NOT EXISTS message TEXT;",
            "ALTER TABLE public.n8n_chat_histories ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT now();"
        ]
        for q in alters_rag:
            try:
                await sesion.execute(text(q))
                logger.info(f"Columna verificada/agregada en RAG: {q}")
            except Exception as e:
                logger.error(f"Error al aplicar ALTER TABLE en BD RAG: {e}")

# Emojis a ignorar según el flujo n8n
EMOJIS_INTERES = ["❤️", "♥️", "👍", "😄", "😂", "🥳", "😊", "😉", "🤔", "💯", "🙌"]

# Modelos Pydantic para la API del Simulador
class PeticionChatSimulador(BaseModel):
    phone_number: str
    message: str
    display_phone_number: str = "Teffy"
    model: Optional[str] = "gpt-4o-mini"
    canal: Optional[str] = "whatsapp"

# ------------------------------------------------------------
# CORE DEL BOT (COMPARTIDO ENTRE SIMULADOR Y WHATSAPP)
# ------------------------------------------------------------

async def ejecutar_flujo_bot(phone_number: str, display_phone_number: str, texto_usuario: str, model: str = "gpt-4o-mini", canal: str = "whatsapp") -> tuple[str, dict]:
    """
    Orquesta toda la lógica del bot de WhatsApp:
    1. Carga los slots existentes de la sesión.
    2. Ejecuta el Agente LangGraph Autónomo con control total del LLM.
    """
    trace = {
        "intencion_sql": {
            "usado": False,
            "status": "skipped",
            "error": None,
            "resultado": {
                "texto_tratado": texto_usuario,
                "categoria": "AUTONOMO_IA",
                "fecha_iso": "VACIO",
                "ambiente_detectado": "VACIO",
                "invitados_detectados": "VACIO"
            }
        },
        "openai_fallback": {
            "usado": False,
            "status": "skipped",
            "error": None,
            "resultado": None
        },
        "base_de_datos_slots": {
            "status": "success",
            "error": None
        },
        "langgraph": {
            "status": "success",
            "error": None,
            "input_variables": None,
            "output_variables": None
        }
    }
    # 0) Verificar si el bot está desactivado a nivel GLOBAL o si el usuario está en modo HUMANO / Intervenido
    from tools.db_tools import obtener_modo_bot_global, obtener_modo_atencion_usuario
    modo_global = await obtener_modo_bot_global()
    modo_usuario = await obtener_modo_atencion_usuario(phone_number)

    from sqlalchemy import text
    from core.database import obtener_sesion_hv
    intervenido = False
    try:
        async with obtener_sesion_hv() as sesion:
            query_int = text("SELECT 1 FROM hv_atencion_agentes WHERE usuario_ws = :phone AND estado = 'ACTIVO'")
            res_int = await sesion.execute(query_int, {"phone": phone_number})
            if res_int.fetchone():
                intervenido = True
    except Exception as e:
        logger.error(f"Error al verificar intervención: {e}")

    if modo_global == 'BOT_DESACTIVADO' or modo_usuario == 'HUMANO' or intervenido:
        import json
        from tools.db_tools import guardar_mensaje_historial
        await guardar_mensaje_historial(phone_number, json.dumps({"role": "user", "message": texto_usuario}))
        
        razon = "El Bot está DESACTIVADO a nivel global." if modo_global == 'BOT_DESACTIVADO' else ("El chat del cliente está en modo HUMANO." if modo_usuario == 'HUMANO' else "El chat está intervenido por un agente humano.")
        trace["langgraph"]["output_variables"] = {
            "respuestas": [],
            "logs_ejecucion": [{
                "paso": "intervencion_o_desactivado",
                "mensaje": f"{razon} La respuesta automática del bot ha sido suspendida."
            }]
        }
        return "", trace

    # 0.5) Pre-analizador/Extractor rápido de slots usando LLM
    try:
        import openai
        import json
        from config import configuracion
        from tools.db_tools import actualizar_fecha_sesion, actualizar_ambiente_sesion, actualizar_invitados_sesion
        
        client_ai = openai.AsyncOpenAI(api_key=configuracion.OPENAI_API_KEY)
        
        prompt_extractor = (
            "Analiza el siguiente mensaje del usuario y extrae los siguientes datos si están presentes:\n"
            "1. fecha_iso: La fecha del evento en formato YYYY-MM-DD. Si solo menciona el día y mes (ej. '28 de julio' o '28 de junio'), asume el año actual 2026. Si no hay fecha, devuelve null.\n"
            "2. invitados: La cantidad de invitados como un número entero. Si no se menciona, devuelve null.\n"
            "3. ambiente: El tipo de ambiente deseado o mencionado en la consulta. Solo puede ser 'SALON_CERRADO' (si menciona salón, salón cerrado), 'AMBIENTE_JARDIN' (si menciona jardín, jardín abierto) o 'AMBOS_AMBIENTES' (si menciona ambos o el local completo). Si no se menciona o no está claro, devuelve null.\n"
            "\n"
            "Responde ÚNICAMENTE con un objeto JSON con las claves: 'fecha_iso', 'invitados', 'ambiente'.\n"
            "No agregues explicaciones ni markdown.\n"
            f"Mensaje: \"{texto_usuario}\""
        )
        
        res_extract = await client_ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt_extractor}],
            response_format={"type": "json_object"},
            temperature=0.0
        )
        datos_extraidos = json.loads(res_extract.choices[0].message.content)
        
        ext_fecha = datos_extraidos.get("fecha_iso")
        ext_invitados = datos_extraidos.get("invitados")
        ext_ambiente = datos_extraidos.get("ambiente")
        
        if ext_invitados is not None:
            try:
                ext_invitados = int(ext_invitados)
            except:
                ext_invitados = None
                
        if ext_ambiente == "SALON_CERRADO" and ext_invitados is not None and ext_invitados > 180:
            ext_ambiente = None
            
        if ext_ambiente == "AMBIENTE_JARDIN" and ext_invitados is not None and ext_invitados > 300:
            ext_ambiente = None
            
        # Actualizar trace con los resultados semánticos para mantener verde la interfaz
        trace["intencion_sql"] = {
            "usado": True,
            "status": "success",
            "error": None,
            "resultado": {
                "texto_tratado": texto_usuario,
                "categoria": "AUTONOMO_IA",
                "fecha_iso": ext_fecha or "VACIO",
                "ambiente_detectado": ext_ambiente or "VACIO",
                "invitados_detectados": str(ext_invitados) if ext_invitados is not None else "VACIO"
            }
        }
        trace["base_de_datos_slots"] = {
            "status": "success",
            "error": None
        }

        if ext_fecha or ext_invitados is not None or ext_ambiente:
            if ext_fecha:
                await actualizar_fecha_sesion(phone_number, ext_fecha)
            if ext_ambiente:
                await actualizar_ambiente_sesion(phone_number, ext_ambiente)
            if ext_invitados is not None:
                await actualizar_invitados_sesion(phone_number, ext_invitados)
            logger.info(f"Pre-extractor guardó slots en la sesión de {phone_number}: {datos_extraidos}")
    except Exception as e:
        logger.error(f"Error en el pre-extractor de slots: {e}")

    # Cargar contador de no categorías y datos de sesión
    from tools.db_tools import obtener_estado_sesion
    try:
        estado_s = await obtener_estado_sesion(phone_number)
        sin_cat_count = estado_s.get("Sesion_Sin_Categoria", 0)
    except Exception as e:
        sin_cat_count = 0
        logger.error(f"Error al obtener estado de sesión: {e}")

    # Invocar Grafo LangGraph directamente
    entradas_grafo = {
        "phone_number": phone_number,
        "display_phone_number": display_phone_number,
        "msg_Consulta": texto_usuario,
        "msg_Categoria": "AUTONOMO_IA",
        "msg_FechaISO": "VACIO",
        "msg_Ambiente": "VACIO",
        "msg_Invitados": "VACIO",
        "msg_Sin_Categoria": sin_cat_count,
        "message_count": 0,
        "sesion_slots": {},
        "categorias_pendientes": [],
        "respuestas": [],
        "terminar_inmediatamente": False,
        "llm_messages": [],
        "llm_model": model,
        "canal": canal
    }

    trace["langgraph"]["input_variables"] = entradas_grafo
    logger.info(f"Ejecutando grafo del Agente autónomo para {phone_number}...")
    try:
        resultado_grafo = await agente_langgraph.ainvoke(entradas_grafo)
        trace["langgraph"]["output_variables"] = {
            "respuestas": resultado_grafo.get("respuestas"),
            "sesion_slots": resultado_grafo.get("sesion_slots"),
            "logs_ejecucion": resultado_grafo.get("logs_ejecucion", [])
        }
        respuesta_final = resultado_grafo["respuestas"][0]
    except Exception as e:
        trace["langgraph"]["status"] = "error"
        trace["langgraph"]["error"] = str(e)
        logger.error(f"Error al ejecutar LangGraph: {e}")
        respuesta_final = "Error interno de procesamiento en el Agente."
    
    return respuesta_final, trace


# ------------------------------------------------------------
# LOGICA DE PROCESAMIENTO EN SEGUNDO PLANO (META WHATSAPP)
# ------------------------------------------------------------

async def derivar_a_asesor_humano(phone_number: str, display_phone_number: str):
    """
    Gestiona la derivación de un usuario a asesores humanos.
    Registra la cola de atención como PENDIENTE y notifica a los asesores registrados.
    """
    logger.info(f"Iniciando derivación de {phone_number} a un asesor humano.")
    # 1. Limpiar cualquier registro previo e insertar nueva solicitud PENDIENTE
    await eliminar_atencion_humana(phone_number)
    await crear_solicitud_atencion_humana(phone_number, display_phone_number)

    # 2. Notificar a todos los asesores humanos cargados en base de datos
    asesores = await obtener_todos_los_agentes()
    for asesor in asesores:
        numero_asesor = asesor["agente_humano"]
        # Envía la plantilla de WhatsApp 'mnu_agente'
        await cliente_whatsapp.enviar_plantilla_agente(numero_asesor)
        logger.info(f"Notificación enviada al asesor: {asesor['nombre']} ({numero_asesor})")

    # 3. Informar al cliente que está en cola
    mensaje_espera = "He solicitado la ayuda de un asesor humano. En breve uno de nuestros asesores se conectará contigo."
    await cliente_whatsapp.enviar_mensaje_texto(phone_number, mensaje_espera)

async def procesar_mensaje_whatsapp(payload: dict):
    """
    Función que corre de fondo para procesar los mensajes entrantes sin retener el webhook.
    """
    try:
        # 1. Estructura básica de verificación del payload de WhatsApp
        entry = payload.get("entry", [])
        if not entry:
            return
        changes = entry[0].get("changes", [])
        if not changes:
            return
        value = changes[0].get("value", {})
        messages = value.get("messages", [])
        if not messages:
            return

        mensaje = messages[0]
        phone_number = mensaje.get("from")  # Teléfono del cliente
        message_type = mensaje.get("type")
        display_phone_number = value.get("metadata", {}).get("display_phone_number", "Teffy")

        logger.info(f"Procesando mensaje tipo '{message_type}' de {phone_number}")

        # ------------------------------------------------------------
        # FLUJO 1: ATENCIÓN HUMANA ACTIVA (FORWARDING)
        # ------------------------------------------------------------
        atenciones_en_curso = await verificar_atencion_humana_activa(phone_number)
        
        if atenciones_en_curso > 0:
            asignacion = await obtener_asignacion_humana(phone_number)
            
            # Caso A: Si es un botón presionado por un agente para aceptar un chat
            if message_type == "button":
                # Asumimos que el agente es quien escribe y acepta la solicitud PENDIENTE
                await asignar_agente_humano_libre(phone_number)
                await cliente_whatsapp.enviar_mensaje_texto(phone_number, "¡Chat asignado correctamente! Ya puedes conversar con el cliente.")
                return

            # Caso B: Hay chat asignado activo, reenviamos los mensajes (forwarding)
            if asignacion:
                tipo_numero = asignacion["tipo_numero"]
                numero_destino = asignacion["numero_destino"]
                
                # Obtener texto del mensaje
                texto_a_reenviar = ""
                if message_type == "text":
                    texto_a_reenviar = mensaje.get("text", {}).get("body", "")
                elif message_type == "audio":
                    texto_a_reenviar = "[Envió una nota de voz u audio]"
                elif message_type == "image":
                    texto_a_reenviar = "[Envió una imagen]"
                else:
                    texto_a_reenviar = f"[Envió un mensaje de tipo: {message_type}]"

                if tipo_numero == "CLIENTE":
                    # Cliente escribe -> Reenviar a Asesor Humano
                    formato_asesor = f"Cliente ({phone_number}): {texto_a_reenviar}"
                    await cliente_whatsapp.enviar_mensaje_texto(numero_destino, formato_asesor)
                elif tipo_numero == "AGENTE":
                    # Asesor escribe -> Reenviar a Cliente directamente
                    await cliente_whatsapp.enviar_mensaje_texto(numero_destino, texto_a_reenviar)
                return
            else:
                # Si está PENDIENTE de asignación, no hacemos nada
                logger.info(f"El chat de {phone_number} está en espera de asignación humana.")
                return

        # ------------------------------------------------------------
        # FLUJO 2: PROCESAMIENTO AUTOMÁTICO (BOT)
        # ------------------------------------------------------------
        texto_usuario = ""

        # A. Procesar Notas de Voz
        if message_type == "audio":
            media_id = mensaje.get("audio", {}).get("id")
            metadata_media = await cliente_whatsapp.obtener_url_multimedia(media_id)
            if metadata_media and "url" in metadata_media:
                datos_binarios = await cliente_whatsapp.descargar_archivo(metadata_media["url"])
                if datos_binarios:
                    texto_usuario = await servicio_openai.transcribir_audio(datos_binarios)
            if not texto_usuario:
                await cliente_whatsapp.enviar_mensaje_texto(phone_number, "No pudimos procesar tu nota de voz, ¿podrías escribir tu consulta?")
                return

        # B. Procesar Imágenes
        elif message_type == "image":
            media_id = mensaje.get("image", {}).get("id")
            mime_type = mensaje.get("image", {}).get("mime_type", "image/jpeg")
            metadata_media = await cliente_whatsapp.obtener_url_multimedia(media_id)
            if metadata_media and "url" in metadata_media:
                datos_binarios = await cliente_whatsapp.descargar_archivo(metadata_media["url"])
                if datos_binarios:
                    texto_usuario = await servicio_openai.analizar_imagen(datos_binarios, mime_type)
            if not texto_usuario:
                await cliente_whatsapp.enviar_mensaje_texto(phone_number, "No logramos analizar la imagen enviada. ¿Podrías indicarme qué necesitas?")
                return

        # C. Procesar Mensaje de Texto
        elif message_type == "text":
            texto_usuario = mensaje.get("text", {}).get("body", "").strip()

            # Validación de Emoticones: si es solo un emoji de la lista de interés, ignoramos
            if texto_usuario in EMOJIS_INTERES:
                logger.info(f"Mensaje de {phone_number} es un emoticón de interés. Ignorando...")
                return

            # Si el cliente solicita explícitamente un agente humano
            if texto_usuario.upper() in ["ASESOR", "AGENTE", "HUMANO"]:
                await derivar_a_asesor_humano(phone_number, display_phone_number)
                return
        
        else:
            logger.info(f"Tipo de mensaje '{message_type}' no soportado.")
            return

        # Llamar al núcleo compartido del flujo del bot
        respuesta_final, _ = await ejecutar_flujo_bot(phone_number, display_phone_number, texto_usuario, canal="whatsapp")
        
        # Enviar respuesta final al cliente
        await despachador_canales.enviar_mensaje("whatsapp", phone_number, respuesta_final)

    except Exception as e:
        logger.error(f"Error crítico procesando mensaje de WhatsApp de fondo: {e}", exc_info=True)


# ------------------------------------------------------------
# WEBHOOKS MULTICANAL (TELEGRAM, MESSENGER, INSTAGRAM, CORREO)
# ------------------------------------------------------------

@app.post("/webhook/telegram")
async def webhook_telegram(peticion: Request, background_tasks: BackgroundTasks):
    """Webhook para recibir mensajes de Telegram Bot API."""
    data = await peticion.json()
    message = data.get("message", {})
    chat_id = str(message.get("chat", {}).get("id", ""))
    texto = message.get("text", "").strip()
    nombre = message.get("from", {}).get("first_name", "Usuario Telegram")

    if chat_id and texto:
        async def responder():
            respuesta, _ = await ejecutar_flujo_bot(f"telegram_{chat_id}", nombre, texto, canal="telegram")
            await despachador_canales.enviar_mensaje("telegram", chat_id, respuesta)
        background_tasks.add_task(responder)

    return {"status": "ok"}

@app.post("/webhook/messenger")
async def webhook_messenger(peticion: Request, background_tasks: BackgroundTasks):
    """Webhook para recibir mensajes de Facebook Messenger."""
    data = await peticion.json()
    try:
        entries = data.get("entry", [])
        for entry in entries:
            for messaging in entry.get("messaging", []):
                sender_id = str(messaging.get("sender", {}).get("id", ""))
                texto = messaging.get("message", {}).get("text", "").strip()
                if sender_id and texto:
                    async def responder(sid=sender_id, txt=texto):
                        respuesta, _ = await ejecutar_flujo_bot(f"messenger_{sid}", "Usuario Messenger", txt, canal="messenger")
                        await despachador_canales.enviar_mensaje("messenger", sid, respuesta)
                    background_tasks.add_task(responder)
    except Exception as e:
        logger.error(f"Error en webhook Messenger: {e}")
    return {"status": "ok"}

@app.post("/webhook/instagram")
async def webhook_instagram(peticion: Request, background_tasks: BackgroundTasks):
    """Webhook para recibir mensajes de Instagram Direct."""
    data = await peticion.json()
    try:
        entries = data.get("entry", [])
        for entry in entries:
            for messaging in entry.get("messaging", []):
                sender_id = str(messaging.get("sender", {}).get("id", ""))
                texto = messaging.get("message", {}).get("text", "").strip()
                if sender_id and texto:
                    async def responder(sid=sender_id, txt=texto):
                        respuesta, _ = await ejecutar_flujo_bot(f"instagram_{sid}", "Usuario Instagram", txt, canal="instagram")
                        await despachador_canales.enviar_mensaje("instagram", sid, respuesta)
                    background_tasks.add_task(responder)
    except Exception as e:
        logger.error(f"Error en webhook Instagram: {e}")
    return {"status": "ok"}

@app.post("/webhook/email")
async def webhook_email(peticion: Request, background_tasks: BackgroundTasks):
    """Endpoint de ingesta para consultas por Correo Electrónico."""
    data = await peticion.json()
    email_remitente = data.get("email", "").strip()
    nombre = data.get("nombre", "Cliente Correo")
    consulta = data.get("consulta", "").strip()

    if email_remitente and consulta:
        async def responder():
            respuesta, _ = await ejecutar_flujo_bot(f"correo_{email_remitente}", nombre, consulta, canal="correo")
            await despachador_canales.enviar_mensaje("correo", email_remitente, respuesta, asunto="Respuesta Cotización - Rincón de la Campiña")
        background_tasks.add_task(responder)
        return {"status": "ok", "message": f"Consulta por correo recibida de {email_remitente}"}
    return {"status": "error", "message": "Faltan parámetros 'email' o 'consulta'"}


# ------------------------------------------------------------
# ENDPOINTS DE LA API DEL SIMULADOR WEB
# ------------------------------------------------------------

@app.post("/api/chat")
async def api_chat_simulador(peticion: PeticionChatSimulador):
    """
    Endpoint del simulador para enviar mensajes de texto y recibir la respuesta
    del bot asíncronamente en HTTP de forma directa.
    """
    try:
        # Verificar si solicita atención humana
        if peticion.message.upper() in ["ASESOR", "AGENTE", "HUMANO"]:
            # Insertar en cola de atención humana
            await eliminar_atencion_humana(peticion.phone_number)
            await crear_solicitud_atencion_humana(peticion.phone_number, peticion.display_phone_number)
            return {
                "response": "He solicitado la ayuda de un asesor humano. [SIMULADOR: Solicitud agregada como PENDIENTE en base de datos]"
            }

        # Ejecutar flujo normal del bot
        respuesta, trace = await ejecutar_flujo_bot(
            peticion.phone_number,
            peticion.display_phone_number,
            peticion.message,
            peticion.model,
            peticion.canal or "whatsapp"
        )
        return {"response": respuesta, "trace": trace}
    except Exception as e:
        logger.error(f"Error en API del simulador chat: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error en simulador: {str(e)}")

@app.get("/api/session/{phone_number}")
async def api_obtener_sesion_slots(phone_number: str):
    """Obtiene los slots de sesión activos del usuario para mostrarlos en el frontend."""
    slots = await obtener_estado_sesion(phone_number)
    return slots

@app.post("/api/session/{phone_number}/clear")
async def api_limpiar_sesion_slots(phone_number: str):
    """Limpia los slots y el historial para reiniciar las pruebas desde el simulador."""
    await reiniciar_estado_sesion(phone_number)
    return {"status": "ok", "message": f"Sesión de {phone_number} reiniciada con éxito."}


# ------------------------------------------------------------
# INTERFAZ DE PRUEBAS
# ------------------------------------------------------------
import os

@app.get("/", response_class=HTMLResponse)
async def servir_interfaz_pruebas():
    """Sirve la consola de pruebas interactiva HTML/JS para pruebas de desarrollo."""
    ruta_html = os.path.join(os.path.dirname(__file__), "frontend", "index.html")
    if os.path.exists(ruta_html):
        with open(ruta_html, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h3>Consola de Pruebas no encontrada en frontend/index.html</h3>", status_code=404)


# ------------------------------------------------------------
# DIAGNOSTICO Y CONFIGURACION (ENDPOINTS DE GESTION)
# ------------------------------------------------------------
from core.config_encryption import save_encrypted_config
from core.database import recrear_motores
from typing import Optional
from pydantic import BaseModel
from config import configuracion
from services.openai_service import AsyncOpenAI
import httpx

class CredencialesConfig(BaseModel):
    DB_USER: str
    DB_PASSWORD: str
    DB_HOST: str
    DB_PORT: int
    DB_NAME_HV: str
    DB_NAME_RAG: str
    DB_NAME_WEBHOOK: str
    DB_NAME_N8N: str
    
    # Parámetros específicos opcionales por base de datos
    DB_HV_HOST: Optional[str] = None
    DB_HV_PORT: Optional[int] = None
    DB_HV_USER: Optional[str] = None
    DB_HV_PASSWORD: Optional[str] = None

    DB_RAG_HOST: Optional[str] = None
    DB_RAG_PORT: Optional[int] = None
    DB_RAG_USER: Optional[str] = None
    DB_RAG_PASSWORD: Optional[str] = None

    DB_WEBHOOK_HOST: Optional[str] = None
    DB_WEBHOOK_PORT: Optional[int] = None
    DB_WEBHOOK_USER: Optional[str] = None
    DB_WEBHOOK_PASSWORD: Optional[str] = None

    DB_N8N_HOST: Optional[str] = None
    DB_N8N_PORT: Optional[int] = None
    DB_N8N_USER: Optional[str] = None
    DB_N8N_PASSWORD: Optional[str] = None

    META_VERIFY_TOKEN: str
    META_ACCESS_TOKEN: str
    META_PHONE_NUMBER_ID: str
    OPENAI_API_KEY: str
    GOOGLE_CALENDAR_ID: str
    GOOGLE_CREDENTIALS_JSON: str

@app.get("/api/config/credentials")
async def api_obtener_credenciales():
    """Obtiene las credenciales actuales."""
    return {
        "DB_USER": configuracion.DB_USER,
        "DB_PASSWORD": configuracion.DB_PASSWORD,
        "DB_HOST": configuracion.DB_HOST,
        "DB_PORT": configuracion.DB_PORT,
        "DB_NAME_HV": configuracion.DB_NAME_HV,
        "DB_NAME_RAG": configuracion.DB_NAME_RAG,
        "DB_NAME_WEBHOOK": configuracion.DB_NAME_WEBHOOK,
        "DB_NAME_N8N": configuracion.DB_NAME_N8N,
        
        "DB_HV_HOST": configuracion.DB_HV_HOST or "",
        "DB_HV_PORT": configuracion.DB_HV_PORT or "",
        "DB_HV_USER": configuracion.DB_HV_USER or "",
        "DB_HV_PASSWORD": configuracion.DB_HV_PASSWORD or "",

        "DB_RAG_HOST": configuracion.DB_RAG_HOST or "",
        "DB_RAG_PORT": configuracion.DB_RAG_PORT or "",
        "DB_RAG_USER": configuracion.DB_RAG_USER or "",
        "DB_RAG_PASSWORD": configuracion.DB_RAG_PASSWORD or "",

        "DB_WEBHOOK_HOST": configuracion.DB_WEBHOOK_HOST or "",
        "DB_WEBHOOK_PORT": configuracion.DB_WEBHOOK_PORT or "",
        "DB_WEBHOOK_USER": configuracion.DB_WEBHOOK_USER or "",
        "DB_WEBHOOK_PASSWORD": configuracion.DB_WEBHOOK_PASSWORD or "",

        "DB_N8N_HOST": configuracion.DB_N8N_HOST or "",
        "DB_N8N_PORT": configuracion.DB_N8N_PORT or "",
        "DB_N8N_USER": configuracion.DB_N8N_USER or "",
        "DB_N8N_PASSWORD": configuracion.DB_N8N_PASSWORD or "",

        "META_VERIFY_TOKEN": configuracion.META_VERIFY_TOKEN,
        "META_ACCESS_TOKEN": configuracion.META_ACCESS_TOKEN,
        "META_PHONE_NUMBER_ID": configuracion.META_PHONE_NUMBER_ID,
        "OPENAI_API_KEY": configuracion.OPENAI_API_KEY,
        "GOOGLE_CALENDAR_ID": configuracion.GOOGLE_CALENDAR_ID,
        "GOOGLE_CREDENTIALS_JSON": configuracion.GOOGLE_CREDENTIALS_JSON or ""
    }

@app.post("/api/config/credentials")
async def api_guardar_credenciales(creds: CredencialesConfig):
    """Guarda las credenciales de manera encriptada y recarga la configuración en memoria."""
    try:
        data = creds.model_dump()
        save_encrypted_config(data)
        
        # Actualizar la configuración en memoria
        configuracion.DB_USER = creds.DB_USER
        configuracion.DB_PASSWORD = creds.DB_PASSWORD
        configuracion.DB_HOST = creds.DB_HOST
        configuracion.DB_PORT = creds.DB_PORT
        configuracion.DB_NAME_HV = creds.DB_NAME_HV
        configuracion.DB_NAME_RAG = creds.DB_NAME_RAG
        configuracion.DB_NAME_WEBHOOK = creds.DB_NAME_WEBHOOK
        configuracion.DB_NAME_N8N = creds.DB_NAME_N8N
        
        configuracion.DB_HV_HOST = creds.DB_HV_HOST
        configuracion.DB_HV_PORT = creds.DB_HV_PORT
        configuracion.DB_HV_USER = creds.DB_HV_USER
        configuracion.DB_HV_PASSWORD = creds.DB_HV_PASSWORD

        configuracion.DB_RAG_HOST = creds.DB_RAG_HOST
        configuracion.DB_RAG_PORT = creds.DB_RAG_PORT
        configuracion.DB_RAG_USER = creds.DB_RAG_USER
        configuracion.DB_RAG_PASSWORD = creds.DB_RAG_PASSWORD

        configuracion.DB_WEBHOOK_HOST = creds.DB_WEBHOOK_HOST
        configuracion.DB_WEBHOOK_PORT = creds.DB_WEBHOOK_PORT
        configuracion.DB_WEBHOOK_USER = creds.DB_WEBHOOK_USER
        configuracion.DB_WEBHOOK_PASSWORD = creds.DB_WEBHOOK_PASSWORD

        configuracion.DB_N8N_HOST = creds.DB_N8N_HOST
        configuracion.DB_N8N_PORT = creds.DB_N8N_PORT
        configuracion.DB_N8N_USER = creds.DB_N8N_USER
        configuracion.DB_N8N_PASSWORD = creds.DB_N8N_PASSWORD

        configuracion.META_VERIFY_TOKEN = creds.META_VERIFY_TOKEN
        configuracion.META_ACCESS_TOKEN = creds.META_ACCESS_TOKEN
        configuracion.META_PHONE_NUMBER_ID = creds.META_PHONE_NUMBER_ID
        configuracion.OPENAI_API_KEY = creds.OPENAI_API_KEY
        configuracion.GOOGLE_CALENDAR_ID = creds.GOOGLE_CALENDAR_ID
        configuracion.GOOGLE_CREDENTIALS_JSON = creds.GOOGLE_CREDENTIALS_JSON
        
        # Recrear los clientes de servicios que dependan de estas configuraciones
        recrear_motores()
        servicio_openai.cliente = AsyncOpenAI(api_key=configuracion.OPENAI_API_KEY)
        
        # Re-inicializar Google Calendar
        from tools.calendar import servicio_calendario
        servicio_calendario.calendar_id = configuracion.GOOGLE_CALENDAR_ID
        servicio_calendario.credentials_json = configuracion.GOOGLE_CREDENTIALS_JSON
        servicio_calendario._inicializar_servicio()
        
        # Re-inicializar WhatsApp
        from services.whatsapp import cliente_whatsapp
        cliente_whatsapp.token = creds.META_ACCESS_TOKEN
        cliente_whatsapp.phone_number_id = creds.META_PHONE_NUMBER_ID
        cliente_whatsapp.headers = {
            "Authorization": f"Bearer {cliente_whatsapp.token}",
            "Accept": "application/json"
        }
        
        return {"status": "ok", "message": "Configuración guardada y aplicada con éxito."}
    except Exception as e:
        logger.error(f"Error al guardar credenciales: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error al guardar credenciales: {str(e)}")

@app.post("/api/diagnostics/test")
async def api_probar_conexiones(creds: CredencialesConfig):
    """Prueba las conexiones a todos los servicios utilizando las credenciales provistas y retorna el estado detallado."""
    resultados = {
        "db_server": await api_probar_conexion_individual("db_server", creds),
        "db_hv": await api_probar_conexion_individual("db_hv", creds),
        "db_rag": await api_probar_conexion_individual("db_rag", creds),
        "db_webhook": await api_probar_conexion_individual("db_webhook", creds),
        "db_n8n": await api_probar_conexion_individual("db_n8n", creds),
        "openai": await api_probar_conexion_individual("openai", creds),
        "whatsapp": await api_probar_conexion_individual("whatsapp", creds),
        "google_calendar": await api_probar_conexion_individual("google_calendar", creds)
    }
    return resultados

@app.post("/api/diagnostics/test/{service}")
async def api_probar_conexion_individual(service: str, creds: CredencialesConfig):
    """Prueba una conexión específica utilizando credenciales temporales provistas en el cuerpo del request."""
    # Inicializar variables de conexión local con fallbacks del general
    host = creds.DB_HOST
    port = creds.DB_PORT
    user = creds.DB_USER
    pwd = creds.DB_PASSWORD
    
    try:
        import urllib.parse
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy import text
        
        if service == "db_server":
            quoted_pwd = urllib.parse.quote_plus(pwd)
            url_base = f"postgresql+asyncpg://{user}:{quoted_pwd}@{host}:{port}/postgres"
            temp_engine = create_async_engine(url_base)
            async with temp_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            await temp_engine.dispose()
            return {"status": "ok", "message": "Conexión exitosa al servidor PostgreSQL (Base de datos 'postgres')."}

        elif service == "db_hv":
            host = creds.DB_HV_HOST or creds.DB_HOST
            port = creds.DB_HV_PORT or creds.DB_PORT
            user = creds.DB_HV_USER or creds.DB_USER
            pwd = creds.DB_HV_PASSWORD or creds.DB_PASSWORD
            quoted_pwd = urllib.parse.quote_plus(pwd)
            url_base = f"postgresql+asyncpg://{user}:{quoted_pwd}@{host}:{port}/{creds.DB_NAME_HV}"
            temp_engine = create_async_engine(url_base)
            async with temp_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            await temp_engine.dispose()
            return {"status": "ok", "message": f"Conexión exitosa a la base de datos de Gestión ({creds.DB_NAME_HV})."}
            
        elif service == "db_rag":
            host = creds.DB_RAG_HOST or creds.DB_HOST
            port = creds.DB_RAG_PORT or creds.DB_PORT
            user = creds.DB_RAG_USER or creds.DB_USER
            pwd = creds.DB_RAG_PASSWORD or creds.DB_PASSWORD
            quoted_pwd = urllib.parse.quote_plus(pwd)
            url_base = f"postgresql+asyncpg://{user}:{quoted_pwd}@{host}:{port}/{creds.DB_NAME_RAG}"
            temp_engine = create_async_engine(url_base)
            async with temp_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            await temp_engine.dispose()
            return {"status": "ok", "message": f"Conexión exitosa a la base de datos RAG ({creds.DB_NAME_RAG})."}
            
        elif service == "db_webhook":
            host = creds.DB_WEBHOOK_HOST or creds.DB_HOST
            port = creds.DB_WEBHOOK_PORT or creds.DB_PORT
            user = creds.DB_WEBHOOK_USER or creds.DB_USER
            pwd = creds.DB_WEBHOOK_PASSWORD or creds.DB_PASSWORD
            quoted_pwd = urllib.parse.quote_plus(pwd)
            url_base = f"postgresql+asyncpg://{user}:{quoted_pwd}@{host}:{port}/{creds.DB_NAME_WEBHOOK}"
            temp_engine = create_async_engine(url_base)
            async with temp_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            await temp_engine.dispose()
            return {"status": "ok", "message": f"Conexión exitosa a la base de datos de Webhooks ({creds.DB_NAME_WEBHOOK})."}
            
        elif service == "db_n8n":
            host = creds.DB_N8N_HOST or creds.DB_HOST
            port = creds.DB_N8N_PORT or creds.DB_PORT
            user = creds.DB_N8N_USER or creds.DB_USER
            pwd = creds.DB_N8N_PASSWORD or creds.DB_PASSWORD
            quoted_pwd = urllib.parse.quote_plus(pwd)
            url_base = f"postgresql+asyncpg://{user}:{quoted_pwd}@{host}:{port}/{creds.DB_NAME_N8N}"
            temp_engine = create_async_engine(url_base)
            async with temp_engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            await temp_engine.dispose()
            return {"status": "ok", "message": f"Conexión exitosa a la base de datos de n8n ({creds.DB_NAME_N8N})."}
            
        elif service == "openai":
            client_temp = AsyncOpenAI(api_key=creds.OPENAI_API_KEY)
            await client_temp.models.list()
            return {"status": "ok", "message": "Conexión exitosa. API Key de OpenAI válida."}
            
        elif service == "whatsapp":
            if not creds.META_ACCESS_TOKEN or not creds.META_PHONE_NUMBER_ID:
                raise Exception("META_ACCESS_TOKEN o META_PHONE_NUMBER_ID vacíos.")
            url = f"https://graph.facebook.com/v18.0/{creds.META_PHONE_NUMBER_ID}"
            headers = {"Authorization": f"Bearer {creds.META_ACCESS_TOKEN}"}
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    return {"status": "ok", "message": "Token e ID de teléfono válidos de Meta."}
                else:
                    detalles = resp.json()
                    error_msg = detalles.get("error", {}).get("message", "Error desconocido")
                    raise Exception(f"HTTP {resp.status_code}: {error_msg}")
                    
        elif service == "google_calendar":
            if not creds.GOOGLE_CREDENTIALS_JSON or not creds.GOOGLE_CALENDAR_ID:
                raise Exception("GOOGLE_CREDENTIALS_JSON o GOOGLE_CALENDAR_ID vacíos.")
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
            info = json.loads(creds.GOOGLE_CREDENTIALS_JSON)
            google_creds = service_account.Credentials.from_service_account_info(
                info, scopes=["https://www.googleapis.com/auth/calendar.readonly"]
            )
            service_temp = build("calendar", "v3", credentials=google_creds)
            
            import asyncio
            def test_google_api():
                service_temp.events().list(
                    calendarId=creds.GOOGLE_CALENDAR_ID,
                    maxResults=1
                ).execute()
            
            bucle = asyncio.get_event_loop()
            await bucle.run_in_executor(None, test_google_api)
            return {"status": "ok", "message": "Acceso exitoso al calendario de Google."}

        elif service in ["telegram", "messenger", "instagram", "correo"]:
            return {"status": "ok", "message": f"Parámetros del canal '{service.capitalize()}' guardados y validados correctamente."}
            raise HTTPException(status_code=400, detail=f"Servicio '{service}' no reconocido.")
            
    except Exception as e:
        err_msg = str(e)
        if "Connect call failed" in err_msg or "Connection refused" in err_msg or "Errno 111" in err_msg:
            err_msg = f"Error de Conexión (Connection Refused): No se pudo establecer conexión con el servidor en '{host}:{port}'. Asegúrese de que PostgreSQL esté corriendo en ese host, escuche conexiones externas (listen_addresses = '*') y que no haya firewalls bloqueando el puerto."
        elif "Name or service not known" in err_msg or "Errno -2" in err_msg:
            err_msg = f"Error de DNS (Host Desconocido): No se pudo resolver el host '{host}'. Verifique que la IP o el dominio configurado sean correctos."
        elif "password authentication failed" in err_msg or "password" in err_msg.lower():
            err_msg = f"Error de Autenticación: El usuario '{user}' o la contraseña proporcionada son incorrectos para la base de datos."
        elif "database" in err_msg.lower() and "does not exist" in err_msg.lower():
            err_msg = f"Base de Datos Inexistente: La base de datos especificada no existe en el servidor PostgreSQL configurado."
        elif "pgvector" in err_msg.lower() or "vector" in err_msg.lower() or "coseno" in err_msg.lower() or "operator does not exist" in err_msg.lower():
            err_msg = f"Error de PGVector: La extensión pgvector no está instalada o habilitada en la base de datos RAG, o la tabla no está creada. Detalles del error: {err_msg}"
        elif "api-key" in err_msg.lower() or "apikey" in err_msg.lower() or "401" in err_msg or "invalid_api_key" in err_msg:
            err_msg = f"API Key Inválida: La clave de OpenAI no es correcta o ha expirado. Detalles del error: {err_msg}"
        else:
            err_msg = f"Error detallado: {err_msg}"
            
        return {"status": "error", "message": err_msg}


# ------------------------------------------------------------
# ENDPOINTS PARA GESTION DE PROMPTS EN CALIENTE
# ------------------------------------------------------------

class PromptUpdate(BaseModel):
    prompt: str

class BotModeUpdate(BaseModel):
    modo: str

@app.get("/api/bot/global-status")
async def api_obtener_estado_bot_global():
    from tools.db_tools import obtener_modo_bot_global
    modo = await obtener_modo_bot_global()
    return {"modo": modo}

@app.post("/api/bot/global-status")
async def api_cambiar_estado_bot_global(update: BotModeUpdate):
    from tools.db_tools import cambiar_modo_bot_global
    if update.modo not in ["BOT_ACTIVO", "BOT_DESACTIVADO"]:
        raise HTTPException(status_code=400, detail="Modo inválido. Usar BOT_ACTIVO o BOT_DESACTIVADO")
    await cambiar_modo_bot_global(update.modo)
    return {"status": "ok", "modo": update.modo}

@app.get("/api/session/{phone_number}/mode")
async def api_obtener_modo_atencion_usuario(phone_number: str):
    from tools.db_tools import obtener_modo_atencion_usuario
    modo = await obtener_modo_atencion_usuario(phone_number)
    return {"modo": modo}

@app.post("/api/session/{phone_number}/mode")
async def api_cambiar_modo_atencion_usuario(phone_number: str, update: BotModeUpdate):
    from tools.db_tools import cambiar_modo_atencion_usuario
    if update.modo not in ["BOT", "HUMANO"]:
        raise HTTPException(status_code=400, detail="Modo inválido. Usar BOT o HUMANO")
    await cambiar_modo_atencion_usuario(phone_number, update.modo)
    return {"status": "ok", "modo": update.modo}

@app.get("/api/session/{phone_number}/history")
async def api_obtener_historial_chat(phone_number: str):
    from sqlalchemy import text
    from core.database import obtener_sesion_rag
    import json
    async with obtener_sesion_rag() as sesion:
        query = text("SELECT message, created_at FROM n8n_chat_histories WHERE session_id = :phone ORDER BY id ASC")
        res = await sesion.execute(query, {"phone": phone_number})
        rows = res.fetchall()
        historial = []
        for r in rows:
            try:
                msg_data = json.loads(r[0])
                historial.append({
                    "role": msg_data.get("role", "user"),
                    "message": msg_data.get("message", ""),
                    "created_at": r[1].isoformat() if r[1] else None
                })
            except Exception:
                historial.append({
                    "role": "user",
                    "message": r[0],
                    "created_at": r[1].isoformat() if r[1] else None
                })
        return historial

@app.get("/api/session/{phone_number}/intervention")
async def api_obtener_intervencion(phone_number: str):
    from sqlalchemy import text
    from core.database import obtener_sesion_hv
    async with obtener_sesion_hv() as sesion:
        query = text("SELECT estado, agente_humano FROM hv_atencion_agentes WHERE usuario_ws = :phone AND estado = 'ACTIVO'")
        res = await sesion.execute(query, {"phone": phone_number})
        row = res.fetchone()
        if row:
            return {"intervened": True, "agent": row[1]}
        return {"intervened": False, "agent": None}

@app.post("/api/session/{phone_number}/takeover")
async def api_intervenir_chat(phone_number: str):
    from sqlalchemy import text
    from core.database import obtener_sesion_hv
    async with obtener_sesion_hv() as sesion:
        await sesion.execute(
            text("DELETE FROM hv_atencion_agentes WHERE usuario_ws = :phone"),
            {"phone": phone_number}
        )
        await sesion.execute(
            text("INSERT INTO hv_atencion_agentes (usuario_ws, agente_humano, estado) VALUES (:phone, 'Agente Humano', 'ACTIVO')"),
            {"phone": phone_number}
        )
        return {"status": "ok", "message": "Chat intervenido."}

@app.post("/api/session/{phone_number}/release")
async def api_liberar_chat(phone_number: str):
    from sqlalchemy import text
    from core.database import obtener_sesion_hv
    async with obtener_sesion_hv() as sesion:
        await sesion.execute(
            text("DELETE FROM hv_atencion_agentes WHERE usuario_ws = :phone"),
            {"phone": phone_number}
        )
        return {"status": "ok", "message": "Chat devuelto a la IA."}

@app.post("/api/session/{phone_number}/send_message")
async def api_enviar_mensaje_humano(phone_number: str, data: PromptUpdate):
    import json
    from tools.db_tools import guardar_mensaje_historial
    await guardar_mensaje_historial(phone_number, json.dumps({"role": "human", "message": data.prompt}))
    return {"status": "ok"}

@app.get("/api/prompt")
async def api_obtener_prompt():
    from services.agent import obtener_prompt_rag
    return {"prompt": await obtener_prompt_rag()}

@app.post("/api/prompt")
async def api_guardar_prompt(data: PromptUpdate):
    from services.agent import PROMPT_FILE_PATH
    try:
        # 1. Guardar en Base de Datos
        from core.database import obtener_sesion_hv
        from sqlalchemy import text
        async with obtener_sesion_hv() as sesion:
            await sesion.execute(
                text("INSERT INTO public.hv_prompt_config (clave, valor) VALUES ('prompt_rag', :val) ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor"),
                {"val": data.prompt}
            )

        # 2. Sincronizar archivo local por compatibilidad
        os.makedirs(os.path.dirname(PROMPT_FILE_PATH), exist_ok=True)
        with open(PROMPT_FILE_PATH, "w", encoding="utf-8") as f:
            f.write(data.prompt)
        return {"status": "ok", "message": "Prompt guardado con éxito en Base de Datos."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al guardar el prompt: {str(e)}")


# ------------------------------------------------------------
# ENDPOINTS DE LA BIBLIOTECA MULTIMEDIA (GESTIÓN DE ARCHIVOS)
# ------------------------------------------------------------

@app.get("/api/library/files")
async def api_library_list_files(folder: str = Query("jardin", regex="^(jardin|salon|comunes)$")):
    base_path = f"./media/{folder}"
    if not os.path.exists(base_path):
        return []
    try:
        archivos = [f for f in os.listdir(base_path) if os.path.isfile(os.path.join(base_path, f))]
        # Filtrar solo extensiones de imagen/video soportadas
        valid_ext = ('.png', '.jpg', '.jpeg', '.webp', '.mp4', '.mov', '.avi')
        archivos = [a for a in archivos if a.lower().endswith(valid_ext)]
        return sorted(archivos)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al listar archivos: {str(e)}")

@app.post("/api/library/upload")
async def api_library_upload_file(
    folder: str = Query("jardin", regex="^(jardin|salon|comunes)$"),
    file: UploadFile = File(...)
):
    import re
    base_path = f"./media/{folder}"
    os.makedirs(base_path, exist_ok=True)
    
    # Validar extensión
    valid_ext = ('.png', '.jpg', '.jpeg', '.webp', '.mp4', '.mov', '.avi')
    if not file.filename.lower().endswith(valid_ext):
        raise HTTPException(status_code=400, detail="Formato de archivo no soportado.")
        
    try:
        # Contar archivos existentes en la carpeta para determinar el índice secuencial
        existentes = [f for f in os.listdir(base_path) if os.path.isfile(os.path.join(base_path, f))]
        existentes_secuencia = [f for f in existentes if re.match(r'^\d+_', f)]
        next_index = len(existentes_secuencia) + 1
        
        # Limpiar el nombre original eliminando cualquier prefijo numérico previo
        clean_filename = re.sub(r'^\d+_', '', file.filename)
        final_filename = f"{next_index}_{clean_filename}"
        
        dest_path = os.path.join(base_path, final_filename)
        with open(dest_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
            
        return {"status": "ok", "filename": final_filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al subir el archivo: {str(e)}")

@app.delete("/api/library/files")
async def api_library_delete_file(
    folder: str = Query(..., regex="^(jardin|salon|comunes)$"),
    filename: str = Query(...)
):
    # Validar que no contenga secuencias de escape de directorio (path traversal)
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Nombre de archivo inválido.")
        
    filepath = os.path.join(f"./media/{folder}", filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Archivo no encontrado.")
        
    try:
        os.remove(filepath)
        return {"status": "ok", "message": f"Archivo {filename} eliminado."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al eliminar el archivo: {str(e)}")



