import base64
import logging
from openai import AsyncOpenAI
from config import configuracion

logger = logging.getLogger(__name__)

class ServicioOpenAI:
    """
    Servicio para interactuar con las APIs de OpenAI (Whisper para audio y GPT-4o-mini para visión y clasificación).
    """
    def __init__(self):
        # El cliente asíncrono de OpenAI cargará automáticamente la API key desde config
        self.cliente = AsyncOpenAI(api_key=configuracion.OPENAI_API_KEY)

    async def transcribir_audio(self, datos_audio: bytes, nombre_archivo: str = "audio.ogg") -> str:
        """
        Transcribe un archivo de audio (normalmente en formato OGG/OPUS proveniente de WhatsApp)
        utilizando el modelo Whisper de OpenAI.
        """
        try:
            # Enviamos el archivo en memoria usando la tupla (nombre, bytes)
            respuesta = await self.cliente.audio.transcriptions.create(
                model="whisper-1",
                file=(nombre_archivo, datos_audio),
                response_format="json"
            )
            transcripcion = respuesta.text.strip()
            logger.info("Transcripción de audio completada con éxito.")
            return transcripcion
        except Exception as e:
            logger.error(f"Error al transcribir el audio en OpenAI: {e}")
            raise Exception(f"Fallo en transcripción de audio: {e}")

    async def analizar_imagen(self, datos_imagen: bytes, tipo_mime: str = "image/jpeg") -> str:
        """
        Analiza una imagen enviada por el cliente de WhatsApp utilizando el modelo GPT-4o-mini.
        Identifica lo que el usuario está buscando o necesita según las instrucciones de n8n.
        """
        try:
            # Codificar la imagen a Base64 para enviarla en el mensaje
            imagen_b64 = base64.b64encode(datos_imagen).decode("utf-8")
            url_imagen = f"data:{tipo_mime};base64,{imagen_b64}"

            # Construimos la solicitud para el modelo de visión según las instrucciones del flujo n8n
            respuesta = await self.cliente.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": "Revisa la imagen y luego intenta descubrir que es lo que el cliente necesita basado en la imagen compartida. Debes ser breve y sugerir lo que esta buscando. Debes decir que esta buscando el cliente."
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": url_imagen
                                }
                            }
                        ]
                    }
                ],
                max_tokens=200,
                temperature=0.2
            )
            resultado = respuesta.choices[0].message.content.strip()
            logger.info("Análisis de imagen completado con éxito.")
            return resultado
        except Exception as e:
            logger.error(f"Error al analizar la imagen en OpenAI: {e}")
            raise Exception(f"Fallo en análisis de imagen: {e}")

    async def clasificar_intencion_fallback(self, texto_usuario: str) -> dict:
        """
        Si la base de datos clasifica el mensaje como SIN_CATEGORIA, este método utiliza GPT-4o-mini
        para intentar clasificar la intención en una de las categorías válidas (DISPONIBILIDAD, PRECIOS, INFORMACION).
        """
        prompt_sistema = (
            "Eres un clasificador de intención y extractor de datos para mensajes de clientes sobre un local de eventos.\n\n"
            "Tu tarea es:\n"
            "1. Analizar el texto del cliente y determinar la categoría o categorías de la intención (pueden ser varias unidas por \"_\").\n"
            "   Categorías posibles:\n"
            "   - SALUDO: Saludos, despedidas, agradecimientos (incluso con errores como 'hoika', 'holaa', 'bunas').\n"
            "   - DISPONIBILIDAD: Si pregunta por fechas libres, si se puede reservar, disponibilidad (incluso con errores como 'esta lubre').\n"
            "   - PRECIOS: Si pregunta por costos, cotización, presupuesto, o menciona que quiere realizar un evento (ej. 'es un matrimonio', 'quiero celebrar mi cumple') ya que esto requiere cotización.\n"
            "   - INFORMACION: Si pregunta por ubicación, capacidad, ambientes, cochera, etc.\n"
            "   - SIN_CATEGORIA: Comentarios sin sentido o sin intención clara.\n\n"
            "2. Extraer los siguientes campos (slots) si son mencionados en el texto (corrige errores ortográficos y typos):\n"
            "   - msg_FechaISO: Fecha del evento en formato YYYY-MM-DD. Si no se menciona año, asume el año actual o el siguiente si la fecha ya pasó. Si no hay fecha o no se entiende, devuelve 'VACIO'.\n"
            "   - msg_Ambiente: El ambiente de interés. Opciones: 'SALON_CERRADO', 'AMBIENTE_JARDIN', 'AMBOS_AMBIENTES'. Si no se menciona, devuelve 'VACIO'.\n"
            "   - msg_Invitados: Cantidad de invitados (solo el número en texto, ej. '250'). Si no se menciona, devuelve 'VACIO'.\n\n"
            "Devuelve un objeto JSON estrictamente en este formato:\n"
            "{\n"
            '  "msg_Categoria": "CATEGORIA_1_CATEGORIA_2",\n'
            '  "msg_FechaISO": "YYYY-MM-DD o VACIO",\n'
            '  "msg_Ambiente": "AMBIENTE o VACIO",\n'
            '  "msg_Invitados": "NUMERO o VACIO",\n'
            '  "msg_Consulta": "Texto original"\n'
            "}"
        )
        try:
            respuesta = await self.cliente.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": prompt_sistema},
                    {"role": "user", "content": texto_usuario}
                ],
                response_format={"type": "json_object"},
                temperature=0.1
            )
            import json
            resultado = json.loads(respuesta.choices[0].message.content)
            logger.info(f"Clasificación fallback completada: {resultado}")
            return resultado
        except Exception as e:
            logger.error(f"Error al clasificar intención fallback: {e}")
            # Retornamos un fallback básico seguro
            return {"msg_Categoria": "SIN_CATEGORIA", "msg_Consulta": texto_usuario}

# Instancia global del servicio
servicio_openai = ServicioOpenAI()
