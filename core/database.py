import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from config import configuracion

logger = logging.getLogger(__name__)

# Motores asíncronos de base de datos
motor_hv = create_async_engine(
    configuracion.url_bd_hv,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20
)

motor_rag = create_async_engine(
    configuracion.url_bd_rag,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20
)

motor_webhook = create_async_engine(
    configuracion.url_bd_webhook,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20
)

motor_n8n = create_async_engine(
    configuracion.url_bd_n8n,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20
)

# Fábricas de sesiones asíncronas
sesion_fabrica_hv = async_sessionmaker(
    bind=motor_hv,
    class_=AsyncSession,
    expire_on_commit=False
)

sesion_fabrica_rag = async_sessionmaker(
    bind=motor_rag,
    class_=AsyncSession,
    expire_on_commit=False
)

sesion_fabrica_webhook = async_sessionmaker(
    bind=motor_webhook,
    class_=AsyncSession,
    expire_on_commit=False
)

sesion_fabrica_n8n = async_sessionmaker(
    bind=motor_n8n,
    class_=AsyncSession,
    expire_on_commit=False
)

# Generadores de contexto para sesiones asíncronas
@asynccontextmanager
async def obtener_sesion_hv() -> AsyncGenerator[AsyncSession, None]:
    """Proporciona una sesión asíncrona para la base de datos HV en un bloque de contexto."""
    sesion = sesion_fabrica_hv()
    try:
        yield sesion
        await sesion.commit()
    except Exception as e:
        await sesion.rollback()
        logger.error(f"Error en la sesión HV de base de datos: {e}")
        raise
    finally:
        await sesion.close()

@asynccontextmanager
async def obtener_sesion_rag() -> AsyncGenerator[AsyncSession, None]:
    """Proporciona una sesión asíncrona para la base de datos RAG en un bloque de contexto."""
    sesion = sesion_fabrica_rag()
    try:
        yield sesion
        await sesion.commit()
    except Exception as e:
        await sesion.rollback()
        logger.error(f"Error en la sesión RAG de base de datos: {e}")
        raise
    finally:
        await sesion.close()

@asynccontextmanager
async def obtener_sesion_webhook() -> AsyncGenerator[AsyncSession, None]:
    """Proporciona una sesión asíncrona para la base de datos Webhook en un bloque de contexto."""
    sesion = sesion_fabrica_webhook()
    try:
        yield sesion
        await sesion.commit()
    except Exception as e:
        await sesion.rollback()
        logger.error(f"Error en la sesión de Webhook de base de datos: {e}")
        raise
    finally:
        await sesion.close()

@asynccontextmanager
async def obtener_sesion_n8n() -> AsyncGenerator[AsyncSession, None]:
    """Proporciona una sesión asíncrona para la base de datos n8n en un bloque de contexto."""
    sesion = sesion_fabrica_n8n()
    try:
        yield sesion
        await sesion.commit()
    except Exception as e:
        await sesion.rollback()
        logger.error(f"Error en la sesión de n8n de base de datos: {e}")
        raise
    finally:
        await sesion.close()


def recrear_motores():
    """Recrea los motores y fábricas de sesiones de base de datos usando la configuración actual."""
    global motor_hv, motor_rag, motor_webhook, motor_n8n
    global sesion_fabrica_hv, sesion_fabrica_rag, sesion_fabrica_webhook, sesion_fabrica_n8n

    logger.info("Recreando motores de base de datos con nueva configuración...")

    motor_hv = create_async_engine(
        configuracion.url_bd_hv,
        echo=False,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20
    )
    motor_rag = create_async_engine(
        configuracion.url_bd_rag,
        echo=False,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20
    )
    motor_webhook = create_async_engine(
        configuracion.url_bd_webhook,
        echo=False,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20
    )
    motor_n8n = create_async_engine(
        configuracion.url_bd_n8n,
        echo=False,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20
    )

    sesion_fabrica_hv = async_sessionmaker(
        bind=motor_hv,
        class_=AsyncSession,
        expire_on_commit=False
    )
    sesion_fabrica_rag = async_sessionmaker(
        bind=motor_rag,
        class_=AsyncSession,
        expire_on_commit=False
    )
    sesion_fabrica_webhook = async_sessionmaker(
        bind=motor_webhook,
        class_=AsyncSession,
        expire_on_commit=False
    )
    sesion_fabrica_n8n = async_sessionmaker(
        bind=motor_n8n,
        class_=AsyncSession,
        expire_on_commit=False
    )


