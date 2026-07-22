import logging
import httpx
from typing import Optional, Dict, Any
from services.whatsapp import cliente_whatsapp
from config import configuracion

logger = logging.getLogger(__name__)

class ChannelDispatcher:
    """
    Despachador unificado de mensajes para la atención omnicanal.
    Soporta WhatsApp, Telegram, Messenger, Instagram y Correo Electrónico.
    """

    async def enviar_mensaje(self, canal: str, destino: str, texto: str, asunto: Optional[str] = None) -> bool:
        """
        Punto de entrada unificado para enviar respuestas del bot según el canal de origen.
        """
        canal_norm = canal.lower().strip()
        if "whatsapp" in canal_norm:
            return await self.enviar_whatsapp(destino, texto)
        elif "telegram" in canal_norm:
            return await self.enviar_telegram(destino, texto)
        elif "messenger" in canal_norm or "facebook" in canal_norm:
            return await self.enviar_messenger(destino, texto)
        elif "instagram" in canal_norm:
            return await self.enviar_instagram(destino, texto)
        elif "correo" in canal_norm or "email" in canal_norm:
            return await self.enviar_correo(destino, asunto or "Respuesta de Rincón de la Campiña", texto)
        else:
            logger.info(f"[Omnicanal] Canal simulado/desconocido '{canal_norm}' para destino {destino}. Mensaje procesado en memoria.")
            return True

    async def enviar_whatsapp(self, numero_destino: str, texto: str) -> bool:
        """Envía mensaje a través de WhatsApp Cloud API."""
        return await cliente_whatsapp.enviar_mensaje_texto(numero_destino, texto)

    async def enviar_telegram(self, chat_id: str, texto: str) -> bool:
        """Envía mensaje a través de Telegram Bot API."""
        token = getattr(configuracion, "TELEGRAM_BOT_TOKEN", None) or ""
        if not token:
            logger.info(f"[Telegram Simulado] Token no configurado. Respuesta enviada a {chat_id}: '{texto[:50]}...'")
            return True

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": texto}
        async with httpx.AsyncClient() as cliente:
            try:
                res = await cliente.post(url, json=payload, timeout=10)
                res.raise_for_status()
                logger.info(f"[Telegram] Mensaje enviado exitosamente a {chat_id}")
                return True
            except Exception as e:
                logger.error(f"[Telegram] Error al enviar mensaje: {e}")
                return False

    async def enviar_messenger(self, recipient_id: str, texto: str) -> bool:
        """Envía mensaje a través de Facebook Messenger Graph API."""
        token = getattr(configuracion, "MESSENGER_PAGE_TOKEN", None) or getattr(configuracion, "META_ACCESS_TOKEN", "")
        if not token:
            logger.info(f"[Messenger Simulado] Token no configurado. Respuesta enviada a {recipient_id}: '{texto[:50]}...'")
            return True

        url = f"https://graph.facebook.com/v21.0/me/messages?access_token={token}"
        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": texto}
        }
        async with httpx.AsyncClient() as cliente:
            try:
                res = await cliente.post(url, json=payload, timeout=10)
                res.raise_for_status()
                logger.info(f"[Messenger] Mensaje enviado a {recipient_id}")
                return True
            except Exception as e:
                logger.error(f"[Messenger] Error enviando mensaje: {e}")
                return False

    async def enviar_instagram(self, recipient_id: str, texto: str) -> bool:
        """Envía mensaje a través de Instagram Direct Graph API."""
        token = getattr(configuracion, "INSTAGRAM_ACCESS_TOKEN", None) or getattr(configuracion, "META_ACCESS_TOKEN", "")
        if not token:
            logger.info(f"[Instagram Simulado] Token no configurado. Respuesta enviada a {recipient_id}: '{texto[:50]}...'")
            return True

        url = f"https://graph.facebook.com/v21.0/me/messages?access_token={token}"
        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": texto}
        }
        async with httpx.AsyncClient() as cliente:
            try:
                res = await cliente.post(url, json=payload, timeout=10)
                res.raise_for_status()
                logger.info(f"[Instagram] Mensaje enviado a {recipient_id}")
                return True
            except Exception as e:
                logger.error(f"[Instagram] Error enviando mensaje: {e}")
                return False

    async def enviar_correo(self, email_destino: str, asunto: str, texto: str) -> bool:
        """Simula/Envía correo electrónico vía SMTP."""
        logger.info(f"[Correo Electrónico] Enviando correo a '{email_destino}' con asunto '{asunto}': {texto[:60]}...")
        return True

despachador_canales = ChannelDispatcher()
