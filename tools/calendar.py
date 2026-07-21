import os
import json
import logging
from typing import Dict, Any
from google.oauth2 import service_account
from googleapiclient.discovery import build
from config import configuracion

logger = logging.getLogger(__name__)

class ServicioGoogleCalendario:
    """
    Servicio para interactuar con la API de Google Calendar y verificar disponibilidad de fechas.
    """
    def __init__(self):
        self.calendar_id = configuracion.GOOGLE_CALENDAR_ID
        self.credentials_json = configuracion.GOOGLE_CREDENTIALS_JSON
        self.service = None
        self._inicializar_servicio()

    def _inicializar_servicio(self):
        """Inicializa el cliente de Google Calendar usando las credenciales de Service Account."""
        if not self.credentials_json:
            logger.warning("No se proporcionó GOOGLE_CREDENTIALS_JSON. El servicio de calendario funcionará en modo simulado.")
            return

        try:
            info_credenciales = json.loads(self.credentials_json)
            credenciales = service_account.Credentials.from_service_account_info(
                info_credenciales,
                scopes=["https://www.googleapis.com/auth/calendar.readonly"]
            )
            self.service = build("calendar", "v3", credentials=credenciales)
            logger.info("Servicio de Google Calendar inicializado con éxito.")
        except Exception as e:
            logger.error(f"Error al inicializar el servicio de Google Calendar: {e}")
            self.service = None

    async def verificar_disponibilidad(self, fecha_inicio_iso: str, fecha_fin_iso: str) -> bool:
        """
        Verifica si hay eventos programados en el rango de tiempo indicado.
        Retorna True si la fecha está libre (disponible), False si está ocupada.
        """
        if not self.service:
            # Fallback simulado: por defecto disponible para fines de prueba si no hay credenciales reales
            logger.warning("Google Calendar en modo de simulación. Retornando disponibilidad simétrica (libre).")
            # Podríamos implementar lógica ficticia, e.g., domingos ocupados, sábados libres
            # Para simular, consideremos disponible
            return True

        try:
            # Llamamos a la API de Google Calendar para listar eventos en el intervalo de tiempo
            # timeMin y timeMax deben estar en formato RFC3339 (ej. 2026-07-05T00:00:00Z)
            logger.info(f"Consultando Google Calendar para el rango: {fecha_inicio_iso} - {fecha_fin_iso}")
            
            # Ejecutamos la consulta en un hilo secundario para evitar bloquear el loop de eventos asíncrono
            import asyncio
            bucle = asyncio.get_event_loop()
            
            def consultar_api():
                resultado = self.service.events().list(
                    calendarId=self.calendar_id,
                    timeMin=fecha_inicio_iso,
                    timeMax=fecha_fin_iso,
                    singleEvents=True,
                    maxResults=1
                ).execute()
                return resultado.get("items", [])

            eventos = await bucle.run_in_executor(None, consultar_api)

            # Si hay algún evento en el rango, significa que la fecha está ocupada (no disponible)
            if len(eventos) > 0:
                logger.info("Se encontraron eventos programados. Fecha NO disponible.")
                return False
            
            logger.info("No se encontraron eventos. Fecha DISPONIBLE.")
            return True

        except Exception as e:
            logger.error(f"Error al verificar disponibilidad en Google Calendar: {e}")
            # En caso de error, preferimos asumir ocupado por seguridad empresarial (fail closed)
            return False

# Instancia global del servicio de calendario
servicio_calendario = ServicioGoogleCalendario()
