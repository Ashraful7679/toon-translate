
"""
Toon Translator - Python Basic
Usage: python translator.py --image your_comic.jpg --output result.jpg
"""
import argparse, cv2, easyocr, numpy as np
from PIL import Image, ImageDraw, ImageFont
import os

# EasyOCR reader - English detection
reader = easyocr.Reader(['en'], gpu=False)

def detect_texts(image_path):
    result = reader.readtext(image_path, paragraph=False)
    # result = [ (bbox, text, conf), ... ] bbox = [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
    detections = []
    for bbox, text, conf in result:
        if len(text.strip()) < 2: continue
        if conf < 0.3: continue
        xs = [p[0] for p in bbox]
        ys = [p[1] for p in bbox]
        x0, y0 = int(min(xs)), int(min(ys))
        x1, y1 = int(max(xs)), int(max(ys))
        detections.append({"bbox":(x0,y0,x1,y1), "text":text, "conf":conf})
    # sort top to bottom, left to right
    detections.sort(key=lambda d: (d["bbox"][1], d["bbox"][0]))
    return detections

def clean_bbox(img, bbox, pad=6):
    x0,y0,x1,y1 = bbox
    x0 = max(0, x0-pad); y0 = max(0, y0-pad)
    x1 = min(img.shape[1], x1+pad); y1 = min(img.shape[0], y1+pad)
    # For comics, speech bubbles are white - fill white
    cv2.rectangle(img, (x0,y0), (x1,y1), (255,255,255), -1)
    return img

def put_bangla_text(img_pil, bbox, bangla_text):
    x0,y0,x1,y1 = bbox
    W = x1 - x0
    H = y1 - y0
    draw = ImageDraw.Draw(img_pil)
    # Try Noto Sans Bengali Bold
    font_path = None
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansBengali-Bold.ttf",
        "NotoSansBengali-Bold.ttf",
        "C:/Windows/Fonts/Nirmala.ttf"
    ]
    for c in candidates:
        if os.path.exists(c):
            font_path = c
            break
    # Auto fit font size
    fontsize = 36
    while fontsize > 10:
        try:
            font = ImageFont.truetype(font_path, fontsize) if font_path else ImageFont.load_default()
        except:
            font = ImageFont.load_default()
        # simple wrap
        words = bangla_text.split()
        lines = []
        cur = ""
        for w in words:
            test = cur + " " + w if cur else w
            # measure
            bbox_text = draw.textbbox((0,0), test, font=font)
            if bbox_text[2] - bbox_text[0] <= W - 10:
                cur = test
            else:
                if cur: lines.append(cur)
                cur = w
        if cur: lines.append(cur)
        total_h = len(lines) * (fontsize + 4)
        if total_h <= H:
            break
        fontsize -= 2

    # draw centered
    y = y0 + (H - total_h)//2
    for line in lines:
        bbox_text = draw.textbbox((0,0), line, font=font)
        tw = bbox_text[2]-bbox_text[0]
        x = x0 + (W - tw)//2
        draw.text((x, y), line, font=font, fill=(0,0,0), stroke_width=0)
        y += fontsize + 4
    return img_pil

def interactive_translate(image_path, output_path):
    img_cv = cv2.imread(image_path)
    detections = detect_texts(image_path)
    print(f"Found {len(detections)} texts")
    img_pil = Image.fromarray(cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB))
    
    for i, det in enumerate(detections):
        print(f"\n[{i+1}/{len(detections)}] English: {det['text']}")
        bangla = input("বাংলা লেখো (skip লিখলে স্কিপ, q লিখলে বের): ").strip()
        if bangla.lower() == 'q':
            break
        if bangla.lower() == 'skip' or bangla == "":
            print("Skipped")
            continue
        # clean
        img_cv = clean_bbox(img_cv, det["bbox"])
        img_pil = Image.fromarray(cv2.cvtColor(img_cv, cv2.COLOR_BGR2RGB))
        img_pil = put_bangla_text(img_pil, det["bbox"], bangla)
        img_cv = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
        print("Done -> Next")

    cv2.imwrite(output_path, img_cv)
    print(f"\nSaved: {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", default="output_bangla.jpg")
    args = parser.parse_args()
    interactive_translate(args.image, args.output)
