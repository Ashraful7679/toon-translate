from fastapi import FastAPI, UploadFile, File, Form, HTTPException  # pyrefly: ignore [missing-import]
from fastapi.middleware.cors import CORSMiddleware  # pyrefly: ignore [missing-import]
from fastapi.responses import HTMLResponse, StreamingResponse  # pyrefly: ignore [missing-import]
from pydantic import BaseModel  # pyrefly: ignore [missing-import]
from typing import List
import io, json, os, cv2, numpy as np
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
    from deep_translator import GoogleTranslator  # pyrefly: ignore [missing-import]
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
        "/usr/share/fonts/opentype/noto/NotoSansBengali-Regular.ttf",
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


def order_points(box):
    pts = np.array(box, dtype=np.float32)
    if pts.shape != (4, 2):
        x0 = float(np.min(pts[:, 0]))
        y0 = float(np.min(pts[:, 1]))
        x1 = float(np.max(pts[:, 0]))
        y1 = float(np.max(pts[:, 1]))
        return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=np.float32)
    return pts


def preprocess_variants(image):
    """Create OCR-friendly versions without destroying the original image geometry."""
    variants = [image]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Upscaling helps EasyOCR with small comic lettering.
    h, w = gray.shape[:2]
    scale = 2.0
    up = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    # Local contrast enhancement for faded/grey speech bubbles.
    clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
    contrast = clahe.apply(up)
    variants.append(cv2.cvtColor(contrast, cv2.COLOR_GRAY2BGR))

    # Light sharpening.
    blur = cv2.GaussianBlur(contrast, (0, 0), 1.0)
    sharp = cv2.addWeighted(contrast, 1.45, blur, -0.45, 0)
    variants.append(cv2.cvtColor(sharp, cv2.COLOR_GRAY2BGR))

    # Otsu threshold is useful for black text on white bubbles.
    _, otsu = cv2.threshold(contrast, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(cv2.cvtColor(otsu, cv2.COLOR_GRAY2BGR))

    # Adaptive threshold handles uneven comic backgrounds better than one global threshold.
    adaptive = cv2.adaptiveThreshold(
        contrast, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 31, 11
    )
    variants.append(cv2.cvtColor(adaptive, cv2.COLOR_GRAY2BGR))

    return variants


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
    a = ''.join(ch.lower() for ch in a if ch.isalnum())
    b = ''.join(ch.lower() for ch in b if ch.isalnum())
    if not a or not b:
        return 0.0
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a, b).ratio()


def add_detection(results, bbox, text, conf, offset_x=0, offset_y=0, scale_x=1.0, scale_y=1.0):
    text = (text or '').strip()
    if not text:
        return

    pts = order_points(bbox)
    x0 = int(round(float(np.min(pts[:, 0])) / scale_x + offset_x))
    y0 = int(round(float(np.min(pts[:, 1])) / scale_y + offset_y))
    x1 = int(round(float(np.max(pts[:, 0])) / scale_x + offset_x))
    y1 = int(round(float(np.max(pts[:, 1])) / scale_y + offset_y))

    if x1 <= x0 or y1 <= y0:
        return

    # Remove obvious noise while allowing short comic words such as "OK", "NO", "?!".
    if conf < 0.10:
        return
    if len(text) == 1 and not text.isalnum():
        return

    results.append({
        "text": text,
        "conf": float(conf),
        "bbox": [x0, y0, x1, y1]
    })


def merge_detections(results):
    """Merge duplicate boxes produced by overlapping tiles/preprocessing variants."""
    results = sorted(results, key=lambda d: d["conf"], reverse=True)
    kept = []

    for item in results:
        duplicate = False
        for existing in kept:
            iou = bbox_iou(item["bbox"], existing["bbox"])
            sim = text_similarity(item["text"], existing["text"])
            if iou >= 0.35 or (sim >= 0.80 and iou >= 0.15):
                # Keep the stronger OCR result, but use the larger box when it clearly contains it.
                duplicate = True
                if item["conf"] > existing["conf"]:
                    existing.update(item)
                break
        if not duplicate:
            kept.append(item)

    return kept


def detect_text_with_easyocr(img, reader):
    h, w = img.shape[:2]
    raw = []

    # For very tall comic pages, process overlapping vertical tiles. This is the key
    # improvement for small text: EasyOCR sees the lettering at a much larger scale.
    max_tile_h = 1800
    overlap = 220

    tiles = []
    if h <= max_tile_h:
        tiles.append((0, h))
    else:
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
        variants = preprocess_variants(tile)

        for variant_index, variant in enumerate(variants):
            vh, vw = variant.shape[:2]
            scale_x = vw / float(tile_w)
            scale_y = vh / float(tile_h)

            try:
                results = reader.readtext(
                    variant,
                    paragraph=False,
                    detail=1,
                    text_threshold=0.25,
                    low_text=0.15,
                    link_threshold=0.20,
                    mag_ratio=1.0,
                    canvas_size=3500,
                    slope_ths=0.5,
                    ycenter_ths=0.7,
                    height_ths=0.7,
                    width_ths=0.7,
                    add_margin=0.08,
                    decoder="greedy"
                )
            except Exception as err:
                print(f"EasyOCR variant {variant_index} error on tile {tile_y0}:{tile_y1}: {err}")
                continue

            for bbox, text, conf in results:
                add_detection(
                    raw,
                    bbox,
                    text,
                    conf,
                    offset_x=0,
                    offset_y=tile_y0,
                    scale_x=scale_x,
                    scale_y=scale_y
                )

    return merge_detections(raw)


def detect_speech_bubbles(img):
    """Fallback only for locating likely text regions; text itself stays blank."""
    try:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        _, thresh = cv2.threshold(blur, 215, 255, cv2.THRESH_BINARY)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        h_img, w_img = img.shape[:2]
        bubbles = []
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            area = w * h
            if 50 <= w <= int(w_img * 0.85) and 30 <= h <= int(h_img * 0.8) and area > 800:
                aspect = w / float(h)
                if 0.35 <= aspect <= 8.0:
                    bubbles.append({
                        "text": "",
                        "conf": 0.0,
                        "bbox": [x, y, x + w, y + h]
                    })
        return bubbles[:30]
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

    h, w = img.shape[:2]
    print(f"OCR image received: {w}x{h}")

    detections = []
    reader = get_ocr_reader()
    if reader is not None:
        try:
            detections = detect_text_with_easyocr(img, reader)
            print(f"EasyOCR detections: {len(detections)}")
        except Exception as err:
            print("OCR Error:", err)
    else:
        print("EasyOCR reader unavailable")

    # Do not replace failed OCR with fake text. Bubble detection is only a visual fallback.
    # It is intentionally used only when absolutely no OCR result exists.
    if len(detections) == 0:
        print("EasyOCR returned 0 text detections. Running bubble-region fallback...")
        detections = detect_speech_bubbles(img)

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
    import uvicorn  # pyrefly: ignore [missing-import]
    uvicorn.run(app, host="0.0.0.0", port=8000)
