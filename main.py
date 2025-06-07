from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from typing import Optional, List
import base64
import sqlite3
import pytesseract
from PIL import Image
import io
import asyncio
import hashlib
import time
import json
import os
from contextlib import asynccontextmanager
from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("App startup: initializing resources if needed")
    yield
    print("App shutdown: cleaning up resources if needed")

app = FastAPI(lifespan=lifespan)

DB_PATH = "tds_virtual_ta_fts.db"
TABLE_NAME = "content_fts"
GITHUB_GPT_TOKEN = os.getenv("GITHUB_TOKEN")
AZURE_ENDPOINT = "https://models.github.ai/inference"
MODEL_NAME = "openai/gpt-4.1"

ocr_cache = {}

def get_sha256_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def extract_text_from_image_sync(image_data: bytes) -> str:
    image = Image.open(io.BytesIO(image_data))
    return pytesseract.image_to_string(image)

async def extract_text_from_image_async(image_data: bytes) -> str:
    return await asyncio.to_thread(extract_text_from_image_sync, image_data)

async def query_llm_async(question: str, context: str) -> str:
    try:
        client = ChatCompletionsClient(
            endpoint=AZURE_ENDPOINT,
            credential=AzureKeyCredential(GITHUB_GPT_TOKEN),
        )

        response = await asyncio.to_thread(client.complete, messages=[
            SystemMessage("You are a helpful TA for the Tools in Data Science course."),
            UserMessage(f"{question}\n\nReference context:\n{context}")
        ],
        temperature=1,
        top_p=1,
        model=MODEL_NAME)

        return response.choices[0].message.content
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM API call failed: {e}")

def get_relevant_context(question: str, top_k: int = 3):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute(f"""
            SELECT url, description FROM {TABLE_NAME}
            WHERE content_fts MATCH ? LIMIT ?
        """, (question, top_k))
        rows = cursor.fetchall()
    except Exception:
        rows = []
    finally:
        conn.close()
    return rows

def clean_promptfoo_payload(data: dict | str) -> dict:
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            return {"question": "Malformed input received."}

    question = data.get("question", "")
    image = data.get("image", None)

    if "{{" in question or "}}" in question:
        question = "Please replace this with a valid question."

    if isinstance(image, str) and ("{{" in image or "}}" in image):
        image = None

    return {"question": question, "image": image}

@app.post("/api/")
async def answer_question(request: Request):
    try:
        raw = await request.body()
        try:
            json_data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON body")

        data = clean_promptfoo_payload(json_data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Request error: {str(e)}")

    question = data.get("question")
    if not question:
        raise HTTPException(status_code=400, detail="Missing 'question'")

    image_b64 = data.get("image")
    extracted_text = ""

    if image_b64:
        try:
            image_bytes = base64.b64decode(image_b64)
            img_hash = get_sha256_hash(image_bytes)
            if img_hash in ocr_cache:
                extracted_text = ocr_cache[img_hash]
            else:
                extracted_text = await extract_text_from_image_async(image_bytes)
                ocr_cache[img_hash] = extracted_text
            question += "\n" + extracted_text
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Image decoding failed: {str(e)}")

    rows = get_relevant_context(question)
    context = "\n\n".join([desc for _, desc in rows if desc])
    answer = await query_llm_async(question, context)

    links = [{"url": url, "text": desc[:60] + ("..." if len(desc) > 60 else "")}
             for url, desc in rows if desc and url]

    return JSONResponse(content={"answer": answer, "links": links})

@app.get("/")
def root():
    return {"message": "FastAPI is running on Render!"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=10000)
