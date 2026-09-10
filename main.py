from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from typing import List
import io, json, os, re, cv2, numpy as np
from PIL import Image, ImageDraw, ImageFont

_reader = None


def get_ocr_reader():
    global _reader
    if _reader is None:
        try:
            import easyocr
            _reader = easyocr.Reader(['en'], gpu=False, verbose=False)
        except Exception as e:
            print("OCR Init Error:", e)
            _reader = None
    return _reader


try:
    from deep_translator import GoogleTranslator
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
        "/usr/share/fonts/truetype/noto/NotoSansBengali-Bold.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansBengali-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf",
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


def bbox_iou(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0, ix1 - ix0), max(0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0, ax1 - ax0) * max(0, ay1 - ay0)
    area_b = max(0, bx1 - bx0) * max(0, by1 - by0)
    return inter / float(area_a + area_b - inter + 1e-6)


def text_similarity(a, b):
    from difflib import SequenceMatcher
    a = ''.join(ch.lower() for ch in a if ch.isalnum())
    b = ''.join(ch.lower() for ch in b if ch.isalnum())
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def clean_ocr_text(text):
    text = re.sub(r'\s+', ' ', (text or '')).strip()
    return text


def looks_like_real_english_text(text, conf, bbox, image_w, image_h):
    text = clean_ocr_text(text)
    if not text or conf < 0.22:
        return False

    # Keep normal comic punctuation, digits and English letters.
    allowed = sum(1 for ch in text if ch.isascii() and (ch.isalnum() or ch in " .,!?'-:;()&%+$#/@"))
    visible = sum(1 for ch in text if not ch.isspace())
    if visible == 0 or allowed / float(visible) < 0.80:
        return False

    # EasyOCR sometimes hallucinates extremely long strings over artwork.
    if len(text) > 120:
        return False

    # Reject obvious repeated-character noise.
    compact = re.sub(r'\s+', '', text.lower())
    if len(compact) >= 8 and len(set(compact)) <= 2:
        return False

    x0, y0, x1, y1 = bbox
    bw = max(1, x1 - x0)
    bh = max(1, y1 - y0)

    # Ignore boxes that are effectively the whole panel/image.
    if bw > image_w * 0.75 and bh > image_h * 0.30:
        return False
    if bw * bh > image_w * image_h * 0.20:
        return False

    # Text boxes should not be absurdly tall compared with their width.
    if bh > bw * 8 and len(compact) < 12:
        return False

    return True


def preprocess_variants(tile):
    """Only use OCR-friendly variants. Binary threshold images are deliberately avoided
    because they produced many false regions on the comic artwork."""
    variants = [tile]
    gray = cv2.cvtColor(tile, cv2.COLOR_BGR2GRAY)
    up = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    contrast = clahe.apply(up)
    variants.append(cv2.cvtColor(contrast, cv2.COLOR_GRAY2BGR))

    blur = cv2.GaussianBlur(contrast, (0, 0), 1.0)
    sharp = cv2.addWeighted(contrast, 1.35, blur, -0.35, 0)
    variants.append(cv2.cvtColor(sharp, cv2.COLOR_GRAY2BGR))

    return variants


def add_detection(results, bbox, text, conf, tile_y0, scale_x, scale_y, image_w, image_h):
    text = clean_ocr_text(text)
    pts = np.asarray(bbox, dtype=np.float32)
    if pts.size == 0:
        return

    x0 = int(round(float(np.min(pts[:, 0])) / scale_x))
    y0 = int(round(float(np.min(pts[:, 1])) / scale_y + tile_y0))
    x1 = int(round(float(np.max(pts[:, 0])) / scale_x))
    y1 = int(round(float(np.max(pts[:, 1])) / scale_y + tile_y0))

    x0 = max(0, min(image_w - 1, x0))
    y0 = max(0, min(image_h - 1, y0))
    x1 = max(0, min(image_w, x1))
    y1 = max(0, min(image_h, y1))

    bbox_out = [x0, y0, x1, y1]
    if not looks_like_real_english_text(text, float(conf), bbox_out, image_w, image_h):
        return

    results.append({
        "text": text,
        "conf": float(conf),
        "bbox": bbox_out
    })


def merge_detections(results):
    results = sorted(results, key=lambda d: d["conf"], reverse=True)
    kept = []

    for item in results:
        duplicate_index = None
        for i, existing in enumerate(kept):
            iou = bbox_iou(item["bbox"], existing["bbox"])
            sim = text_similarity(item["text"], existing["text"])
            if iou >= 0.30 or (sim >= 0.78 and iou >= 0.10):
                duplicate_index = i
                break

        if duplicate_index is None:
            kept.append(item)
        else:
            existing = kept[duplicate_index]
            if item["conf"] > existing["conf"]:
                kept[duplicate_index] = item

    return kept


def detect_text_with_easyocr(img, reader):
    h, w = img.shape[:2]
    raw = []

    # 720x3500 and similar comic pages are split so small lettering gets enough pixels.
    max_tile_h = 1500
    overlap = 250
    tiles = []

    y = 0
    while y < h:
        y1 = min(h, y + max_tile_h)
        tiles.append((y, y1))
        if y1 >= h:
            break
        y = y1 - overlap

    for tile_y0, tile_y1 in tiles:
        tile = img[tile_y0:tile_y1, 0:w]
        tile_h, tile_w = tile.shape[:2]

        for variant_index, variant in enumerate(preprocess_variants(tile)):
            vh, vw = variant.shape[:2]
            scale_x = vw / float(tile_w)
            scale_y = vh / float(tile_h)

            try:
                results = reader.readtext(
                    variant,
                    paragraph=False,
                    detail=1,
                    text_threshold=0.35,
                    low_text=0.25,
                    link_threshold=0.30,
                    mag_ratio=1.0,
                    canvas_size=2500,
                    slope_ths=0.45,
                    ycenter_ths=0.6,
                    height_ths=0.6,
                    width_ths=0.6,
                    add_margin=0.05,
                    decoder="greedy"
                )
            except Exception as err:
                print(f"EasyOCR error tile={tile_y0}:{tile_y1}, variant={variant_index}: {err}")
                continue

            for bbox, text, conf in results:
                add_detection(
                    raw, bbox, text, conf,
                    tile_y0, scale_x, scale_y, w, h
                )

    return merge_detections(raw)


@app.post("/api/detect")
async def detect(file: UploadFile = File(...)):
    if not file:
        raise HTTPException(status_code=400, detail="No image provided")

    contents = await file.read()
    nparr = np.frombuffer(contents, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(status_code=400, detail="Invalid image file")

    h, w = img.shape[:2]
    print(f"OCR image received: {w}x{h}")

    detections = []
    reader = get_ocr_reader()
    if reader is None:
        raise HTTPException(status_code=500, detail="EasyOCR could not be initialized")

    try:
        detections = detect_text_with_easyocr(img, reader)
        print(f"EasyOCR final text detections: {len(detections)}")
    except Exception as err:
        print("OCR Error:", err)
        raise HTTPException(status_code=500, detail=f"OCR failed: {err}")

    # IMPORTANT: no speech-bubble contour fallback here.
    # It was producing boxes around artwork/blank regions and looked like fake text detection.
    detections.sort(key=lambda d: (d["bbox"][1], d["bbox"][0]))
    for i, d in enumerate(detections):
        d["id"] = i

    return {"detections": detections, "width": w, "height": h}


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
            try:
                import requests
                r = requests.get(
                    "https://api.mymemory.translated.net/get",
                    params={"q": text, "langpair": "en|bn"},
                    timeout=6
                )
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

    for item in items:
        bbox = item.get("bbox")
        translation = item.get("translation", "").strip()
        if not bbox or not translation:
            continue

        x0, y0, x1, y1 = map(int, bbox)
        pad = 4
        rx0 = max(0, x0 - pad)
        ry0 = max(0, y0 - pad)
        rx1 = min(img_cv.shape[1], x1 + pad)
        ry1 = min(img_cv.shape[0], y1 + pad)
        cv2.rectangle(img_cv, (rx0, ry0), (rx1, ry1), (255, 255, 255), -1)

    img_pil = Image.fromarray(cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img_pil)

    for item in items:
        bbox = item.get("bbox")
        bangla_text = item.get("translation", "").strip()
        if not bbox or not bangla_text:
            continue

        x0, y0, x1, y1 = map(int, bbox)
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
            for word in words:
                test = cur + " " + word if cur else word
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
                    cur = word

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
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
