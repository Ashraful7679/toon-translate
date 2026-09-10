
"""
Advanced: Bubble Detection + Better Inpaint
- Contour detection to find speech bubbles (white blobs with black border)
- EasyOCR for text
- Telea Inpaint for clean
"""
import cv2, easyocr, numpy as np
from PIL import Image, ImageDraw, ImageFont
import os

reader = easyocr.Reader(['en'])

def find_bubbles(image_path):
    img = cv2.imread(image_path, 0)
    # Threshold white bubbles
    _, thresh = cv2.threshold(img, 200, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    bubbles = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if 2000 < area < 200000: # filter bubble size
            x,y,w,h = cv2.boundingRect(cnt)
            if w > 40 and h > 20:
                bubbles.append((x,y,x+w,y+h))
    return bubbles

def detect_with_bubbles(image_path):
    bubbles = find_bubbles(image_path)
    texts = reader.readtext(image_path)
    # Associate text inside bubble
    final = []
    for bbox, t, conf in texts:
        xs = [p[0] for p in bbox]; ys = [p[1] for p in bbox]
        x0,y0,x1,y1 = int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))
        # find parent bubble
        parent = None
        for bx0,by0,bx1,by1 in bubbles:
            if bx0 <= x0 and by0 <= y0 and bx1 >= x1 and by1 >= y1:
                parent = (bx0,by0,bx1,by1)
                break
        final.append({"text_bbox":(x0,y0,x1,y1), "bubble": parent or (x0,y0,x1,y1), "text":t})
    return final

def clean_with_inpaint(img, bubble_bbox):
    x0,y0,x1,y1 = bubble_bbox
    mask = np.zeros(img.shape[:2], dtype=np.uint8)
    cv2.rectangle(mask, (x0,y0), (x1,y1), 255, -1)
    # Telea inpaint (better than white fill for colored comics)
    inpainted = cv2.inpaint(img, mask, 3, cv2.INPAINT_TELEA)
    # For white bubbles, also fill white to ensure clean
    cv2.rectangle(inpainted, (x0+2,y0+2), (x1-2,y1-2), (255,255,255), -1)
    return inpainted

# ... similar put_bangla_text as basic, but use bubble bbox for centering

print("Advanced module loaded. Use detect_with_bubbles() + clean_with_inpaint()")
