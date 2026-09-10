
from fastapi import FastAPI, UploadFile, File, Form, HTTPException # pyrefly: ignore [missing-import] # type: ignore
from fastapi.middleware.cors import CORSMiddleware # pyrefly: ignore [missing-import] # type: ignore
from fastapi.responses import HTMLResponse, StreamingResponse # pyrefly: ignore [missing-import] # type: ignore
from pydantic import BaseModel # pyrefly: ignore [missing-import] # type: ignore
from typing import List, Optional
import io, json, os, cv2, numpy as np
from PIL import Image, ImageDraw, ImageFont

_reader = None

def get_ocr_reader():
    global _reader
    if _reader is None:
        try:
            import easyocr
            _reader = easyocr.Reader(['en'], gpu=False)
        except Exception as e:
            print("OCR Init Error:", e)
            _reader = None
    return _reader


try:
    from deep_translator import GoogleTranslator # pyrefly: ignore [missing-import] # type: ignore
    translator = GoogleTranslator(source='en', target='bn')
except Exception as e:
    translator = None
    print(f"DeepTranslator Init Warning: {e}")

app = FastAPI(title="Toon Translation Studio")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def find_fonts():
    candidates = [
        "NotoSansBengali-Bold.ttf",
        "NotoSansBengali-Regular.ttf",
        "C:/Windows/Fonts/Nirmala.ttf",
        "C:/Windows/Fonts/NirmalaB.ttf",
        "C:/Windows/Fonts/kalpurush.ttf",
        "C:/Windows/Fonts/solaimanlipi.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansBengali-Bold.ttf"
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None

FONT_PATH = find_fonts()

class AutoTranslateRequest(BaseModel):
    texts: List[str]

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    with open("index.html", "r", encoding="utf-8") as f:
        return f.read()

def detect_speech_bubbles(img):
    try:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 215, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        h_img, w_img = img.shape[:2]
        bubbles = []
        
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            if 30 <= w <= int(w_img * 0.85) and 20 <= h <= int(h_img * 0.8):
                aspect = w / float(h)
                if 0.3 <= aspect <= 10.0 and (w * h) > 400:
                    bubbles.append({
                        "id": len(bubbles),
                        "text": f"Speech Bubble ({w}x{h})",
                        "conf": 0.80,
                        "bbox": [x, y, x + w, y + h]
                    })
        return bubbles
    except Exception as e:
        print("Bubble detection error:", e)
        return []

@app.post("/api/detect")
async def detect(file: UploadFile = File(...)):
    if not file:
        raise HTTPException(status_code=400, detail="No image provided")
    
    contents = await file.read()
    nparr = np.frombuffer(contents, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    if img is None:
        raise HTTPException(status_code=400, detail="Invalid image file")

    detections = []
    reader = get_ocr_reader()
    if reader is not None:
        try:
            results = reader.readtext(img, paragraph=False)
            for idx, (bbox, text, conf) in enumerate(results):
                text_clean = text.strip()
                if len(text_clean) < 1 or conf < 0.2:
                    continue
                xs = [p[0] for p in bbox]
                ys = [p[1] for p in bbox]
                x0, y0 = int(min(xs)), int(min(ys))
                x1, y1 = int(max(xs)), int(max(ys))
                detections.append({
                    "id": idx,
                    "text": text_clean,
                    "conf": float(conf),
                    "bbox": [x0, y0, x1, y1]
                })
        except Exception as err:
            print("OCR Error:", err)

    # Fallback to OpenCV speech bubble contour detector if OCR returns no text
    if len(detections) == 0:
        print("EasyOCR returned 0 detections. Running OpenCV contour bubble detector fallback...")
        bubbles = detect_speech_bubbles(img)
        detections.extend(bubbles)

    # Sort detections top-to-bottom, left-to-right (comic panel reading order)
    detections.sort(key=lambda d: (d["bbox"][1] // 40, d["bbox"][0]))
    for i, d in enumerate(detections):
        d["id"] = i

    return {"detections": detections, "width": img.shape[1], "height": img.shape[0]}

@app.post("/api/auto-translate")
async def auto_translate(req: AutoTranslateRequest):
    results = []
    for text in req.texts:
        if not text.strip():
            results.append("")
            continue
        translated = ""
        if translator:
            try:
                translated = translator.translate(text)
            except Exception as e:
                print("Translation Error:", e)
        if not translated:
            # Fallback to MyMemory
            try:
                import requests
                r = requests.get(f"https://api.mymemory.translated.net/get?q={text}&langpair=en|bn", timeout=4)
                data = r.json()
                translated = data.get("responseData", {}).get("translatedText", "")
            except Exception:
                translated = ""
        results.append(translated)
    return {"translations": results}

@app.post("/api/render")
async def render_image(
    file: UploadFile = File(...),
    items_json: str = Form(...)
):
    contents = await file.read()
    nparr = np.frombuffer(contents, np.uint8)
    img_cv = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    
    if img_cv is None:
        raise HTTPException(status_code=400, detail="Invalid image")

    items = json.loads(items_json)
    
    # 1. Clean speech bubble areas (white rectangle fill with padding)
    for item in items:
        bbox = item.get("bbox")
        translation = item.get("translation", "").strip()
        if not bbox or not translation:
            continue
        x0, y0, x1, y1 = bbox
        pad = 4
        rx0 = max(0, x0 - pad)
        ry0 = max(0, y0 - pad)
        rx1 = min(img_cv.shape[1], x1 + pad)
        ry1 = min(img_cv.shape[0], y1 + pad)
        cv2.rectangle(img_cv, (rx0, ry0), (rx1, ry1), (255, 255, 255), -1)

    # 2. Render Bangla text using PIL
    img_pil = Image.fromarray(cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img_pil)

    for item in items:
        bbox = item.get("bbox")
        bangla_text = item.get("translation", "").strip()
        if not bbox or not bangla_text:
            continue
        x0, y0, x1, y1 = bbox
        W = max(10, x1 - x0)
        H = max(10, y1 - y0)

        fontsize = min(40, max(12, int(H * 0.4)))
        lines = []
        font = None

        while fontsize >= 10:
            try:
                font = ImageFont.truetype(FONT_PATH, fontsize) if FONT_PATH else ImageFont.load_default()
            except Exception:
                font = ImageFont.load_default()

            words = bangla_text.split()
            lines = []
            cur = ""
            for w in words:
                test = cur + " " + w if cur else w
                try:
                    tb = draw.textbbox((0, 0), test, font=font)
                    tw = tb[2] - tb[0]
                except Exception:
                    tw = len(test) * (fontsize * 0.6)
                
                if tw <= W + 10:
                    cur = test
                else:
                    if cur:
                        lines.append(cur)
                    cur = w
            if cur:
                lines.append(cur)

            line_height = fontsize * 1.2
            total_h = len(lines) * line_height
            if total_h <= H + 10 or fontsize <= 10:
                break
            fontsize -= 2

        line_height = fontsize * 1.2
        total_h = len(lines) * line_height
        curr_y = y0 + max(0, (H - total_h) / 2)

        for line in lines:
            try:
                tb = draw.textbbox((0, 0), line, font=font)
                tw = tb[2] - tb[0]
            except Exception:
                tw = len(line) * (fontsize * 0.6)
            curr_x = x0 + max(0, (W - tw) / 2)
            draw.text((curr_x, curr_y), line, font=font, fill=(0, 0, 0))
            curr_y += line_height

    final_cv = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
    _, encoded_img = cv2.imencode(".png", final_cv)
    return StreamingResponse(io.BytesIO(encoded_img.tobytes()), media_type="image/png")

if __name__ == "__main__":
    import uvicorn # pyrefly: ignore [missing-import] # type: ignore
    uvicorn.run(app, host="0.0.0.0", port=8000)

