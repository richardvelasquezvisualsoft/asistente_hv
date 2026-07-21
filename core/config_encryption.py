import base64
import os
import json
import logging

logger = logging.getLogger(__name__)

# Clave de encriptación interna
ENCRYPTION_KEY = "TeffySecretKey2026_hv_asistente_virtual!"
ENC_FILE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env.enc")

def xor_crypt(data: str, key: str) -> str:
    """Cifra/Descifra una cadena de texto usando un XOR simple con clave rotativa."""
    key_len = len(key)
    output = []
    for i, char in enumerate(data):
        key_char = key[i % key_len]
        output.append(chr(ord(char) ^ ord(key_char)))
    return "".join(output)

def encrypt_data(data: str) -> str:
    """Encripta texto a una representación legible en Base64."""
    crypted = xor_crypt(data, ENCRYPTION_KEY)
    return base64.b64encode(crypted.encode('utf-8')).decode('utf-8')

def decrypt_data(encrypted_data: str) -> str:
    """Desencripta texto a partir de su representación en Base64."""
    try:
        decoded = base64.b64decode(encrypted_data.encode('utf-8')).decode('utf-8')
        return xor_crypt(decoded, ENCRYPTION_KEY)
    except Exception as e:
        logger.error(f"Error al desencriptar credenciales: {e}")
        return ""

def save_encrypted_config(config_dict: dict):
    """Guarda el diccionario de configuración encriptado en el archivo .env.enc."""
    try:
        json_str = json.dumps(config_dict)
        encrypted_str = encrypt_data(json_str)
        with open(ENC_FILE_PATH, "w", encoding="utf-8") as f:
            f.write(encrypted_str)
        logger.info("Configuración guardada de manera encriptada con éxito.")
    except Exception as e:
        logger.error(f"Error al guardar configuración encriptada: {e}")
        raise

def load_encrypted_config() -> dict:
    """Carga y desencripta la configuración desde .env.enc."""
    if not os.path.exists(ENC_FILE_PATH):
        return {}
    try:
        with open(ENC_FILE_PATH, "r", encoding="utf-8") as f:
            encrypted_str = f.read().strip()
        if not encrypted_str:
            return {}
        json_str = decrypt_data(encrypted_str)
        return json.loads(json_str)
    except Exception as e:
        logger.error(f"Error al cargar configuración encriptada: {e}")
        return {}
