import logging
from typing import List, Dict, Any
from sqlalchemy import text
from core.database import obtener_sesion_rag
from services.openai_service import servicio_openai

logger = logging.getLogger(__name__)

class PGVectorRAG:
    """
    Herramienta RAG que se conecta a la base de datos de PostgreSQL con extensión PGVector.
    Genera embeddings usando OpenAI y recupera información relevante del local de eventos.
    """
    def __init__(self):
        self.nombre_tabla = "n8n_documents"
        self.dimensiones = 1536
        self.modelo_embeddings = "text-embedding-3-small"

    async def obtener_embeddings(self, texto: str) -> List[float]:
        """
        Genera el vector de embeddings para el texto de consulta
        utilizando la API asíncrona de OpenAI.
        """
        try:
            respuesta = await servicio_openai.cliente.embeddings.create(
                model=self.modelo_embeddings,
                input=texto,
                dimensions=self.dimensiones
            )
            return respuesta.data[0].embedding
        except Exception as e:
            logger.error(f"Error al generar embeddings con OpenAI: {e}")
            raise

    async def buscar_informacion(self, consulta_usuario: str, top_k: int = 12) -> str:
        """
        Busca los top_k fragmentos de información más similares en la tabla n8n_documents
        utilizando la distancia coseno (<=>) de PGVector.
        """
        try:
            # 1. Obtener el embedding de la consulta del usuario
            vector = await self.obtener_embeddings(consulta_usuario)
            
            # Formatear el vector como string de lista PostgreSQL: '[val1, val2, ...]'
            vector_str = f"[{','.join(map(str, vector))}]"

            # 2. Ejecutar búsqueda de similitud coseno en la base de datos RAG
            query = text(
                f"SELECT text, metadata "
                f"FROM {self.nombre_tabla} "
                f"ORDER BY embedding <=> CAST(:embedding AS vector) "
                f"LIMIT :limit"
            )
            
            async with obtener_sesion_rag() as sesion:
                resultado = await sesion.execute(query, {
                    "embedding": vector_str,
                    "limit": top_k
                })
                filas = resultado.fetchall()

            # 3. Formatear y consolidar los fragmentos recuperados para el contexto del Agente
            if not filas:
                logger.info("No se encontró información relevante en el RAG para la consulta dada.")
                return "No hay información adicional disponible en nuestra base de conocimientos para responder."

            contextos = []
            for i, fila in enumerate(filas, 1):
                contenido = fila[0]
                metadata = fila[1] if fila[1] else {}
                contextos.append(f"Documento {i}:\n{contenido}")

            contexto_final = "\n\n".join(contextos)
            logger.info(f"Búsqueda RAG completada con éxito. Se recuperaron {len(filas)} fragmentos.")
            return contexto_final

        except Exception as e:
            logger.error(f"Error al realizar la búsqueda semántica RAG: {e}")
            return "Ocurrió un error al consultar la base de datos de conocimiento."

# Instancia global del buscador RAG
buscador_rag = PGVectorRAG()
