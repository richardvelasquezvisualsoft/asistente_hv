import asyncio
from services.agent import workflow, EstadoAgente
from langgraph.graph import StateGraph

async def main():
    agent = workflow.compile()
    
    state = {
        "phone_number": "12345",
        "msg_Consulta": "hola",
        "msg_Categoria": "TEST",
        "msg_FechaISO": "VACIO",
        "msg_Ambiente": "VACIO",
        "msg_Invitados": "VACIO",
        "msg_Sin_Categoria": 0,
        "message_count": 0,
    }
    
    # Run a dummy graph test or just check how Langgraph updates it
    # We can mock the LLM or just run it directly if we have openai key.
    pass

if __name__ == "__main__":
    asyncio.run(main())
