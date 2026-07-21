import hmac
import hashlib
import logging
from fastapi import Header, HTTPException, Request
from config import configuracion

logger = logging.getLogger(__name__)

# Secreto de la aplicación Meta para validar firmas (opcional en config si no se usa estrictamente)
META_APP_SECRET = getattr(configuracion, "META_APP_SECRET", None)

async def verificar_firma_meta(request: Request, x_hub_signature_256: str = Header(None)) -> bool:
    """
    Verifica que la firma X-Hub-Signature-256 recibida en el encabezado
    coincida con la firma HMAC-SHA256 generada usando el META_APP_SECRET.
    """
    if not META_APP_SECRET:
        # Si no se configuró el secreto de la app, registramos una advertencia pero dejamos pasar
        # TODO(security): Implementar verificación estricta una vez que el secreto esté configurado.
        return True

    if not x_hub_signature_256:
        logger.warning("Falta el encabezado X-Hub-Signature-256 en la solicitud.")
        raise HTTPException(status_code=401, detail="Falta firma de seguridad")

    # Extraer firma (viene con formato sha256=...)
    partes = x_hub_signature_256.split("=")
    if len(partes) != 2 or partes[0] != "sha256":
        raise HTTPException(status_code=400, detail="Formato de firma no válido")

    firma_recibida = partes[1]
    cuerpo = await request.body()

    # Calcular firma esperada
    firma_esperada = hmac.new(
        META_APP_SECRET.encode("utf-8"),
        cuerpo,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(firma_recibida, firma_esperada):
        logger.error("La firma de la solicitud no coincide con la esperada.")
        raise HTTPException(status_code=401, detail="Firma de seguridad inválida")

    return True

def verificar_token_desafio(verify_token: str) -> bool:
    """Valida el token de verificación recibido durante el handshake del webhook de Meta."""
    return verify_token == configuracion.META_VERIFY_TOKEN
