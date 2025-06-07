import os
import time
import requests
import asyncio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from typing import Optional, List
import base64
import sqlite3
import pytesseract
from PIL import Image
import io
import hashlib
import json
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("App startup: initializing resources if needed")
    yield
    print("App shutdown: cleaning up resources if needed")

app = FastAPI(lifespan=lifespan)

DB_PATH = "tds_virtual_ta_fts.db"
TABLE_NAME = "content_fts"

# Updated: Use GitHub Token env var here
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_API_URL = "https://models.github.ai/inference"
MODEL_NAME = "openai/o4-mini"

ocr_cache = {}

def get_sha256_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def extract_text_from_image_sync(image_data: bytes) -> str:
    image = Image.open(io.BytesIO(image_data))
    return pytesseract.image_to_string(image)

async def extract_text_from_image_async(image_data: bytes) -> str:
    return await asyncio.to_thread(extract_text_from_image_sync, image_data)

# Updated query_llm_async function for GitHub token usage and model endpoint
async def query_llm_async(question: str, context: str) -> str:
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": "You are a helpful TA for the Tools in Data Science course."},
            {"role": "user", "content": f"{question}\n\nReference context:\n{context}"}
        ]
    }

    def post_request_with_retry():
        for attempt in range(3):
            try:
                response = requests.post(GITHUB_API_URL, headers=headers, json=payload, timeout=60)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                if attempt == 2:
                    raise HTTPException(status_code=502, detail=f"LLM API request failed after 3 attempts: {e}")
                time.sleep(2)

    data = await asyncio.get_event_loop().run_in_executor(None, post_request_with_retry)

    try:
        # GitHub API returns choices similarly, but just verify structure if needed
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise HTTPException(status_code=502, detail=f"Unexpected LLM API response structure: {e} | {data}")

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
