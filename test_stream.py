import asyncio
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import json
import httpx
import uvicorn

app = FastAPI()

async def mock_generator():
    try:
        await asyncio.sleep(1)
        yield "data: {\"answer\": \"hello\"}\n\n"
        await asyncio.sleep(1)
        raise httpx.ReadTimeout("Mock timeout")
    except Exception as e:
        yield f"data: {json.dumps({'answer': f'⚠️ Error: {str(e)}', 'done': True, 'stats': {}, 'sources': []})}\n\n"

@app.get("/stream")
async def stream():
    return StreamingResponse(mock_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8099)
