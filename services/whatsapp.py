import logging
import httpx
from typing import Dict, Any, Optional
from config import configuracion

logger = logging.getLogger(__name__)

class ClienteWhatsAppMeta:
    """
    Cliente asíncrono para interactuar con la Graph API de Meta (WhatsApp Cloud API).
    Permite descargar archivos multimedia (audio, imágenes) y enviar mensajes de texto y plantillas.
    """
    def __init__(self):
        self.token = configuracion.META_ACCESS_TOKEN
        self.phone_number_id = configuracion.META_PHONE_NUMBER_ID
        self.url_base_api = "https://graph.facebook.com/v21.0"
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json"
        }

    async def obtener_url_multimedia(self, media_id: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene la URL de descarga y metadatos de un archivo multimedia (audio o imagen)
        usando su ID único generado por WhatsApp.
        """
        url = f"{self.url_base_api}/{media_id}"
        async with httpx.AsyncClient() as cliente:
            try:
                respuesta = await cliente.get(url, headers=self.headers)
                respuesta.raise_for_status()
                datos = respuesta.json()
                logger.info(f"Se obtuvieron los metadatos multimedia para ID: {media_id}")
                return datos
            except httpx.HTTPStatusError as e:
                logger.error(f"Error HTTP de Meta al obtener URL multimedia para ID {media_id}: {e.response.text}")
            except Exception as e:
                logger.error(f"Error inesperado al obtener URL multimedia de Meta: {e}")
            return None

    async def descargar_archivo(self, url_descarga: str) -> Optional[bytes]:
        """
        Descarga el archivo binario desde la URL provista por la API de Graph de Meta.
        """
        # Las descargas requieren el mismo token de autorización de Meta
        async with httpx.AsyncClient() as cliente:
            try:
                respuesta = await cliente.get(url_descarga, headers=self.headers)
                respuesta.raise_for_status()
                logger.info("Archivo multimedia descargado correctamente.")
                return respuesta.content
            except httpx.HTTPStatusError as e:
                logger.error(f"Error HTTP al descargar archivo multimedia: {e.response.text}")
            except Exception as e:
                logger.error(f"Error inesperado al descargar archivo: {e}")
            return None

    async def enviar_mensaje_texto(self, numero_destino: str, texto: str) -> bool:
        """
        Envía un mensaje de texto simple al número de WhatsApp indicado.
        """
        url = f"{self.url_base_api}/{self.phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": numero_destino,
            "type": "text",
            "text": {
                "body": texto
            }
        }
        async with httpx.AsyncClient() as cliente:
            try:
                respuesta = await cliente.post(url, headers=self.headers, json=payload)
                respuesta.raise_for_status()
                logger.info(f"Mensaje enviado con éxito a {numero_destino}")
                return True
            except httpx.HTTPStatusError as e:
                logger.error(f"Error HTTP de Meta al enviar mensaje de texto a {numero_destino}: {e.response.text}")
            except Exception as e:
                logger.error(f"Error inesperado al enviar mensaje de texto: {e}")
            return False

    async def enviar_plantilla_agente(self, numero_agente: str) -> bool:
        """
        Envía la plantilla de notificación 'mnu_agente' a un asesor humano cuando se solicita su intervención.
        """
        url = f"{self.url_base_api}/{self.phone_number_id}/messages"
        payload = {
            "messaging_product": "whatsapp",
            "to": numero_agente,
            "type": "template",
            "template": {
                "name": "mnu_agente",
                "language": {
                    "code": "es_PE"
                }
            }
        }
        async with httpx.AsyncClient() as cliente:
            try:
                respuesta = await cliente.post(url, headers=self.headers, json=payload)
                respuesta.raise_for_status()
                logger.info(f"Plantilla 'mnu_agente' enviada con éxito al agente humano: {numero_agente}")
                return True
            except httpx.HTTPStatusError as e:
                logger.error(f"Error HTTP al enviar plantilla de agente a {numero_agente}: {e.response.text}")
            except Exception as e:
                logger.error(f"Error inesperado al enviar plantilla de agente: {e}")
            return False

# Instancia global del cliente WhatsApp
cliente_whatsapp = ClienteWhatsAppMeta()
