from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from services.ws_llm import stream_llm_response
router = APIRouter(prefix="/api")


@router.websocket("/ws/chat")
async def chat_ws(websocket: WebSocket):
    await websocket.accept()

    try:
        while True:
            data = await websocket.receive_json()
            query = data.get("query")

            if not query:
                await websocket.send_json({"error": "empty query"})
                continue

            async for chunk in stream_llm_response(query):
                await websocket.send_json({
                    "type": "token",
                    "data": chunk
                })

            await websocket.send_json({
                "type": "done"
            })

    except WebSocketDisconnect:
        print("Client disconnected")