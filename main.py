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
            print('OCR Init Error:', e)
            _reader = None
    return _reader

try:
    from deep_translator import GoogleTranslator
    translator = GoogleTranslator(source='en', target='bn')
except Exception as e:
    translator = None
    print(f'DeepTranslator Init Warning: {e}')

app = FastAPI(title='Toon Translation Studio')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])

FONT_CACHE = '/tmp/NotoSansBengali-Regular.ttf'
FONT_URL = 'https://github.com/googlefonts/noto-fonts/raw/main/hinted/ttf/NotoSansBengali/NotoSansBengali-Regular.ttf'

def find_fonts():
    candidates = [
        os.path.join(os.path.dirname(__file__), 'NotoSansBengali-Regular.ttf'),
        os.path.join(os.path.dirname(__file__), 'fonts', 'NotoSansBengali-Regular.ttf'),
        FONT_CACHE,
        'NotoSansBengali-Regular.ttf', 'NotoSansBengali-Bold.ttf',
        'C:/Windows/Fonts/Nirmala.ttf', 'C:/Windows/Fonts/NirmalaB.ttf',
        'C:/Windows/Fonts/kalpurush.ttf', 'C:/Windows/Fonts/solaimanlipi.ttf',
        '/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf',
        '/usr/share/fonts/truetype/noto/NotoSansBengali-Bold.ttf',
        '/usr/share/fonts/opentype/noto/NotoSansBengali-Regular.ttf',
    ]
    for c in candidates:
        if os.path.exists(c): return c
    return None

FONT_PATH = find_fonts()

def ensure_bengali_font():
    global FONT_PATH
    if FONT_PATH and os.path.exists(FONT_PATH): return FONT_PATH
    try:
        import requests
        r = requests.get(FONT_URL, timeout=15)
        r.raise_for_status()
        if len(r.content) > 10000:
            with open(FONT_CACHE, 'wb') as f: f.write(r.content)
            FONT_PATH = FONT_CACHE
            return FONT_PATH
    except Exception as e:
        print('Bengali font download warning:', e)
    return None

class AutoTranslateRequest(BaseModel):
    texts: List[str]

@app.get('/', response_class=HTMLResponse)
async def serve_index():
    with open('index.html', 'r', encoding='utf-8') as f: html = f.read()
    html += r'''
<script>
(() => {
  const state = { manual: {}, mode: 'bubble' };
  const key = () => String(typeof currentIndex !== 'undefined' ? currentIndex : -1);
  const items = () => state.manual[key()] || (state.manual[key()] = []);
  function currentImageFile(){
    try{ if(typeof imageList!=='undefined'&&typeof currentIndex!=='undefined'&&imageList[currentIndex]?.file) return Promise.resolve(imageList[currentIndex].file); }catch(e){}
    const img=document.getElementById('mainImage'); if(!img||!img.src)return null;
    return fetch(img.src).then(r=>r.blob()).then(b=>new File([b],'toon-page.png',{type:b.type||'image/png'}));
  }
  function addToolbar(){
    const toolbar=document.querySelector('.stage-toolbar'); if(!toolbar||document.getElementById('bubbleModeBtn'))return;
    const box=document.createElement('div'); box.style.cssText='display:flex;align-items:center;gap:6px;margin-left:auto';
    box.innerHTML='<button id="bubbleModeBtn" class="btn btn-primary" style="padding:7px 11px;font-size:12px">💬 Bubble Select: ON</button><button id="clearBubbleBtn" class="btn" style="padding:7px 11px;font-size:12px">🗑️ Clear Bubbles</button>';
    toolbar.appendChild(box);
    document.getElementById('bubbleModeBtn').onclick=()=>{state.mode=state.mode==='bubble'?'off':'bubble';const b=document.getElementById('bubbleModeBtn');b.textContent=state.mode==='bubble'?'💬 Bubble Select: ON':'🖱️ Bubble Select: OFF';b.classList.toggle('btn-primary',state.mode==='bubble');};
    document.getElementById('clearBubbleBtn').onclick=()=>{state.manual[key()]=[];renderManualSidebar();drawManualOverlay();};
  }
  async function selectBubble(ev){
    if(state.mode!=='bubble')return; const img=document.getElementById('mainImage'); if(!img||!img.naturalWidth)return;
    if(ev.target.closest&&ev.target.closest('.bbox-rect'))return;
    const r=img.getBoundingClientRect(); const x=Math.round((ev.clientX-r.left)*img.naturalWidth/r.width),y=Math.round((ev.clientY-r.top)*img.naturalHeight/r.height);
    if(x<0||y<0||x>=img.naturalWidth||y>=img.naturalHeight)return;
    try{if(window.showSpinner)window.showSpinner('বাবল সিলেক্ট করা হচ্ছে...');const file=await currentImageFile();if(!file)throw new Error('Image unavailable');const fd=new FormData();fd.append('file',file);fd.append('x',x);fd.append('y',y);const res=await fetch('/api/select-bubble',{method:'POST',body:fd});const data=await res.json();if(!res.ok)throw new Error(data.detail||'Bubble not found');const exists=items().some(it=>{const a=it.bbox,b=data.bbox;return Math.abs(a[0]-b[0])<12&&Math.abs(a[1]-b[1])<12&&Math.abs(a[2]-b[2])<12&&Math.abs(a[3]-b[3])<12;});if(!exists)items().push({id:Date.now(),text:'',conf:1,bbox:data.bbox,polygon:data.polygon||[],translation:'',manual:true});renderManualSidebar();drawManualOverlay();}
    catch(e){console.warn(e);alert('এই জায়গায় পূর্ণ বাবল পাওয়া যায়নি। বাবলের সাদা/ভেতরের অংশে আবার ক্লিক করুন।');}finally{if(window.hideSpinner)window.hideSpinner();}
  }
  function drawManualOverlay(){const svg=document.getElementById('overlaySvg'),img=document.getElementById('mainImage');if(!svg||!img||!img.naturalWidth)return;svg.setAttribute('viewBox',`0 0 ${img.naturalWidth} ${img.naturalHeight}`);svg.innerHTML='';items().forEach((it,i)=>{const[x0,y0,x1,y1]=it.bbox;const rect=document.createElementNS('http://www.w3.org/2000/svg','rect');rect.setAttribute('x',x0);rect.setAttribute('y',y0);rect.setAttribute('width',Math.max(1,x1-x0));rect.setAttribute('height',Math.max(1,y1-y0));rect.setAttribute('class','bbox-rect active');rect.style.fill='rgba(16,185,129,.10)';rect.style.stroke='#10b981';rect.addEventListener('click',e=>{e.stopPropagation();focusBubbleAndCard(i);});svg.appendChild(rect);});}
  function scrollStageToBubble(bbox){const stage=document.getElementById('stageView'),img=document.getElementById('mainImage'),wrapper=document.getElementById('canvasWrapper');if(!stage||!img||!wrapper||!img.naturalWidth||!bbox||bbox.length!==4)return;const scale=img.getBoundingClientRect().width/img.naturalWidth;if(!isFinite(scale)||scale<=0)return;const cx=((Number(bbox[0])+Number(bbox[2]))/2)*scale,cy=((Number(bbox[1])+Number(bbox[3]))/2)*scale;stage.scrollTo({left:Math.max(0,wrapper.offsetLeft+cx-stage.clientWidth/2),top:Math.max(0,wrapper.offsetTop+cy-stage.clientHeight/2),behavior:'smooth'});}
  function focusBubbleAndCard(i){const it=items()[i];if(!it)return;scrollStageToBubble(it.bbox);const el=document.getElementById('bubble-card-'+i);if(el){el.classList.add('active');el.scrollIntoView({behavior:'smooth',block:'nearest'});const inp=el.querySelector('textarea');if(inp)inp.focus({preventScroll:true});}}
  function bindManualTextarea(card,i){const ta=card.querySelector('textarea');if(!ta)return;ta.addEventListener('focus',()=>scrollStageToBubble(items()[i]?.bbox));ta.addEventListener('click',()=>scrollStageToBubble(items()[i]?.bbox));ta.addEventListener('input',()=>{items()[i].translation=ta.value;});ta.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();const n=document.querySelector('#sidebarContent textarea[data-bubble-index="'+(i+1)+'"]');if(n)n.focus();}});}
  function renderManualSidebar(){const wrap=document.getElementById('sidebarContent'),count=document.getElementById('detectionCount');if(!wrap)return;const list=items();if(count)count.textContent=list.length;if(!list.length){wrap.innerHTML='<div class="empty-state"><div class="empty-icon">💬</div><p>Bubble Select চালু রেখে ছবির প্রতিটি পূর্ণ বাবলের ভিতরে একবার ক্লিক করুন।</p></div>';return;}wrap.innerHTML='';list.forEach((it,i)=>{const card=document.createElement('div');card.className='item-card';card.id='bubble-card-'+i;card.innerHTML=`<div class="item-header"><span class="item-badge">Bubble ${i+1}</span><div class="item-actions"><button class="btn-icon" title="এই বাবল মুছুন">🗑️</button></div></div><div class="original-text">Manual bubble • ${it.bbox[2]-it.bbox[0]} × ${it.bbox[3]-it.bbox[1]} px</div><div class="input-wrapper"><textarea class="translation-input" data-bubble-index="${i}" placeholder="এখানে বাংলা অনুবাদ লিখুন...">${it.translation||''}</textarea></div><div class="input-tip"><span>Enter = পরের বাবল</span><span>Unicode + HarfBuzz</span></div>`;card.querySelector('.btn-icon').onclick=()=>{list.splice(i,1);renderManualSidebar();drawManualOverlay();};wrap.appendChild(card);bindManualTextarea(card,i);});}
  async function renderManual(){const list=items().filter(it=>it.translation&&it.translation.trim());if(!list.length){alert('কমপক্ষে একটি বাবলের বাংলা অনুবাদ লিখুন।');return;}try{if(window.showSpinner)window.showSpinner('বাবলের মধ্যে অনুবাদ বসানো হচ্ছে...');const file=await currentImageFile();if(!file)throw new Error('Image unavailable');const fd=new FormData();fd.append('file',file);fd.append('items_json',JSON.stringify(list));const res=await fetch('/api/render',{method:'POST',body:fd});if(!res.ok)throw new Error(await res.text());const blob=await res.blob(),url=URL.createObjectURL(blob);try{if(typeof imageList!=='undefined'&&typeof currentIndex!=='undefined'&&imageList[currentIndex])imageList[currentIndex].renderedUrl=url;}catch(e){}const img=document.getElementById('mainImage');if(typeof activeView!=='undefined')activeView='rendered';document.getElementById('btnOriginal')?.classList.remove('active');document.getElementById('btnRendered')?.classList.add('active');img.src=url;img.onload=()=>{if(typeof applyZoom==='function')applyZoom();drawManualOverlay();};}catch(e){console.error(e);alert('Render করা যায়নি: '+e.message);}finally{if(window.hideSpinner)window.hideSpinner();}}
  function install(){addToolbar();const img=document.getElementById('mainImage');if(img&&!img.dataset.bubbleBound){img.dataset.bubbleBound='1';img.addEventListener('click',selectBubble);}const renderBtn=[...document.querySelectorAll('button')].find(b=>b.textContent.includes('রেন্ডার কার্টুন'))||[...document.querySelectorAll('button')].find(b=>b.textContent.includes('রেন্ডার'));if(renderBtn&&!renderBtn.dataset.manualRender){renderBtn.dataset.manualRender='1';renderBtn.addEventListener('click',e=>{if(items().length){e.stopImmediatePropagation();renderManual();}},true);}const observer=new MutationObserver(()=>{addToolbar();const im=document.getElementById('mainImage');if(im&&!im.dataset.bubbleBound){im.dataset.bubbleBound='1';im.addEventListener('click',selectBubble);}});observer.observe(document.body,{childList:true,subtree:true});renderManualSidebar();drawManualOverlay();}
  window.addEventListener('load',()=>setTimeout(install,250));window.toonBubbleManual={renderManual,renderManualSidebar,drawManualOverlay,scrollStageToBubble,focusBubbleAndCard};
})();
</script>
'''
    return HTMLResponse(content=html)

def bbox_iou(a,b):
    ax0,ay0,ax1,ay1=a;bx0,by0,bx1,by1=b;ix0,iy0=max(ax0,bx0),max(ay0,by0);ix1,iy1=min(ax1,bx1),min(ay1,by1);iw,ih=max(0,ix1-ix0),max(0,iy1-iy0);inter=iw*ih
    if inter<=0:return 0.0
    aa=max(0,ax1-ax0)*max(0,ay1-ay0);ab=max(0,bx1-bx0)*max(0,by1-by0);return inter/float(aa+ab-inter+1e-6)

def text_similarity(a,b):
    from difflib import SequenceMatcher
    a=''.join(ch.lower() for ch in a if ch.isalnum());b=''.join(ch.lower() for ch in b if ch.isalnum());return SequenceMatcher(None,a,b).ratio() if a and b else 0.0

def clean_ocr_text(text):return re.sub(r'\s+',' ',(text or '')).strip()

def looks_like_real_english_text(text,conf,bbox,image_w,image_h):
    text=clean_ocr_text(text)
    if not text or conf<0.20:return False
    allowed=sum(1 for ch in text if ch.isascii() and (ch.isalnum() or ch in " .,!?'-:;()&%+$#/@"));visible=sum(1 for ch in text if not ch.isspace())
    if not visible or allowed/float(visible)<0.80 or len(text)>120:return False
    compact=re.sub(r'\s+','',text.lower())
    if len(compact)>=8 and len(set(compact))<=2:return False
    x0,y0,x1,y1=bbox;bw,bh=max(1,x1-x0),max(1,y1-y0)
    if bw>image_w*0.75 and bh>image_h*0.30:return False
    if bw*bh>image_w*image_h*0.20:return False
    return True

def preprocess_variants(tile):
    variants=[tile];gray=cv2.cvtColor(tile,cv2.COLOR_BGR2GRAY);up=cv2.resize(gray,None,fx=2.0,fy=2.0,interpolation=cv2.INTER_CUBIC);clahe=cv2.createCLAHE(clipLimit=2.0,tileGridSize=(8,8));contrast=clahe.apply(up);variants.append(cv2.cvtColor(contrast,cv2.COLOR_GRAY2BGR));blur=cv2.GaussianBlur(contrast,(0,0),1.0);sharp=cv2.addWeighted(contrast,1.35,blur,-0.35,0);variants.append(cv2.cvtColor(sharp,cv2.COLOR_GRAY2BGR));return variants

def add_detection(results,bbox,text,conf,tile_y0,scale_x,scale_y,image_w,image_h):
    text=clean_ocr_text(text);pts=np.asarray(bbox,dtype=np.float32)
    if pts.size==0:return
    x0=int(round(float(np.min(pts[:,0]))/scale_x));y0=int(round(float(np.min(pts[:,1]))/scale_y+tile_y0));x1=int(round(float(np.max(pts[:,0]))/scale_x));y1=int(round(float(np.max(pts[:,1]))/scale_y+tile_y0));x0=max(0,min(image_w-1,x0));y0=max(0,min(image_h-1,y0));x1=max(0,min(image_w,x1));y1=max(0,min(image_h,y1));bbox_out=[x0,y0,x1,y1]
    if looks_like_real_english_text(text,float(conf),bbox_out,image_w,image_h):results.append({'text':text,'conf':float(conf),'bbox':bbox_out})

def merge_detections(results):
    results=sorted(results,key=lambda d:d['conf'],reverse=True);kept=[]
    for item in results:
        duplicate=False
        for existing in kept:
            iou=bbox_iou(item['bbox'],existing['bbox']);sim=text_similarity(item['text'],existing['text'])
            if iou>=0.55 or (iou>=0.25 and sim>=0.65) or (sim>=0.90 and iou>=0.10):duplicate=True;break
        if not duplicate:kept.append(item)
    return kept

@app.post('/api/detect')
async def detect(file:UploadFile=File(...)):
    data=await file.read();arr=np.frombuffer(data,np.uint8);img=cv2.imdecode(arr,cv2.IMREAD_COLOR)
    if img is None:raise HTTPException(400,'Invalid image')
    h,w=img.shape[:2];reader=get_ocr_reader()
    if reader is None:return {'detections':[]}
    results=[];tile_h=1500;overlap=250;ys=[0] if h<=tile_h else list(range(0,max(1,h-tile_h+1),tile_h-overlap))
    if ys[-1]+tile_h<h:ys.append(h-tile_h)
    for y0 in ys:
        y1=min(h,y0+tile_h);tile=img[y0:y1]
        for variant in preprocess_variants(tile):
            sx=variant.shape[1]/tile.shape[1];sy=variant.shape[0]/tile.shape[0]
            try:detections=reader.readtext(variant,paragraph=False,detail=1,text_threshold=0.30,low_text=0.20,link_threshold=0.25,mag_ratio=1.2,canvas_size=3000,slope_ths=0.35,ycenter_ths=0.6,height_ths=0.6,width_ths=0.8,add_margin=0.08,decoder='greedy',rotation_info=[90,180,270])
            except Exception as e:print('OCR Error:',e);continue
            for pts,text,conf in detections:add_detection(results,pts,text,conf,y0,sx,sy,w,h)
    merged=merge_detections(results)
    for i,d in enumerate(merged):d['id']=i
    return {'detections':merged}

@app.post('/api/select-bubble')
async def select_bubble(file:UploadFile=File(...),x:int=Form(...),y:int=Form(...)):
    data=await file.read();arr=np.frombuffer(data,np.uint8);img=cv2.imdecode(arr,cv2.IMREAD_COLOR)
    if img is None:raise HTTPException(400,'Invalid image')
    h,w=img.shape[:2]
    if not(0<=x<w and 0<=y<h):raise HTTPException(400,'Point outside image')
    gray=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY);mask=cv2.inRange(gray,245,255);n,labels,stats,cent=cv2.connectedComponentsWithStats(mask,8);candidates=[]
    for i in range(1,n):
        x0,y0,bw,bh,area=stats[i]
        if area<500 or bw<30 or bh<30 or not(x0<=x<x0+bw and y0<=y<y0+bh):continue
        fill=area/float(max(1,bw*bh))
        if fill<0.35 or bw>0.85*w or bh>0.85*h:continue
        dist=abs((x0+bw/2)-x)+abs((y0+bh/2)-y);candidates.append((dist,area,[int(x0),int(y0),int(x0+bw),int(y0+bh)]))
    if not candidates:raise HTTPException(404,'Full speech bubble not found')
    _,_,bbox=min(candidates,key=lambda z:z[0]);x0,y0,x1,y1=bbox;roi=gray[y0:y1,x0:x1];_,th=cv2.threshold(roi,245,255,cv2.THRESH_BINARY);contours,_=cv2.findContours(th,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE);poly=[]
    if contours:
        c=max(contours,key=cv2.contourArea);eps=0.01*cv2.arcLength(c,True);p=cv2.approxPolyDP(c,eps,True).reshape(-1,2);poly=[[int(px+x0),int(py+y0)] for px,py in p]
    return {'bbox':bbox,'polygon':poly}

# ---------------------------------------------------------------------------
# Bengali rendering: Unicode -> HarfBuzz shaping -> FreeType glyph rasterizing
# ---------------------------------------------------------------------------

def _load_shaper(font_path):
    import uharfbuzz as hb
    import freetype
    with open(font_path, 'rb') as f:
        font_data = f.read()
    hb_face = hb.Face(font_data)
    hb_font = hb.Font(hb_face)
    face = freetype.Face(font_path)
    return hb, freetype, hb_font, face

def _shape_line(text, font_path, size):
    hb, freetype, hb_font, face = _load_shaper(font_path)
    face.set_pixel_sizes(0, int(size))
    hb_font.scale = (int(size * 64), int(size * 64))
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(hb_font, buf, {})
    infos = buf.glyph_infos
    positions = buf.glyph_positions
    glyphs = []
    advance = 0.0
    for info, pos in zip(infos, positions):
        glyphs.append((info.codepoint, pos.x_advance / 64.0, pos.y_advance / 64.0, pos.x_offset / 64.0, pos.y_offset / 64.0))
        advance += pos.x_advance / 64.0
    return face, glyphs, advance

def _line_width(text, font_path, size):
    if not text:
        return 0.0
    return _shape_line(text, font_path, size)[2]

def _wrap_shaped_text(text, font_path, size, max_width):
    text = re.sub(r'[ \t]+', ' ', (text or '').strip())
    if not text:
        return []
    paragraphs = text.split('\n')
    lines = []
    for paragraph in paragraphs:
        words = paragraph.split(' ')
        if not words:
            lines.append('')
            continue
        current = ''
        for word in words:
            candidate = word if not current else current + ' ' + word
            if _line_width(candidate, font_path, size) <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                if _line_width(word, font_path, size) > max_width:
                    part = ''
                    for ch in word:
                        test = part + ch
                        if part and _line_width(test, font_path, size) > max_width:
                            lines.append(part)
                            part = ch
                        else:
                            part = test
                    current = part
                else:
                    current = word
        if current or not lines:
            lines.append(current)
    return lines

def _render_shaped_line(layer, text, font_path, size, x, baseline_y):
    face, glyphs, _ = _shape_line(text, font_path, size)
    pen_x = float(x)
    for glyph_id, x_adv, y_adv, x_off, y_off in glyphs:
        face.load_glyph(int(glyph_id), 0x4)
        bitmap = face.glyph.bitmap
        w = int(bitmap.width); h = int(bitmap.rows)
        if w and h:
            pitch = abs(int(bitmap.pitch))
            raw = bytes(bitmap.buffer)
            if pitch == w:
                mask = Image.frombytes('L', (w, h), raw)
            else:
                packed = bytearray()
                for row in range(h):
                    packed.extend(raw[row * pitch:row * pitch + w])
                mask = Image.frombytes('L', (w, h), bytes(packed))
            gx = int(round(pen_x + face.glyph.bitmap_left + x_off))
            gy = int(round(baseline_y - face.glyph.bitmap_top - y_off))
            ink = Image.new('RGBA', (w, h), (0, 0, 0, 0))
            ink.paste((0, 0, 0, 255), (0, 0, w, h), mask)
            layer.alpha_composite(ink, (gx, gy))
        pen_x += x_adv

def _text_layer(text, font_path, size, max_width):
    lines = _wrap_shaped_text(text, font_path, size, max_width)
    if not lines:
        return None, [], 0, 0
    line_height = max(1, int(size * 1.35))
    widths = [_line_width(line, font_path, size) for line in lines]
    width = max(1, int(np.ceil(max(widths) if widths else 1)))
    height = max(1, line_height * len(lines))
    layer = Image.new('RGBA', (width + 4, height + 4), (0, 0, 0, 0))
    baseline = int(size * 0.95)
    for i, line in enumerate(lines):
        lw = widths[i]
        _render_shaped_line(layer, line, font_path, size, (width - lw) / 2.0 + 2, baseline + i * line_height)
    return layer, lines, width, height

def _fits_circle(text, font_path, size, diameter, padding):
    max_width = max(8, diameter - padding * 2)
    layer, lines, w, h = _text_layer(text, font_path, size, max_width)
    if layer is None:
        return None
    alpha = np.asarray(layer.getchannel('A'))
    ys, xs = np.nonzero(alpha > 8)
    if len(xs) == 0:
        return None
    cx = layer.width / 2.0
    cy = layer.height / 2.0
    radius = diameter / 2.0 - padding
    if radius <= 1:
        return None
    dx = xs - cx
    dy = ys - cy
    if float(np.max(dx * dx + dy * dy)) > radius * radius:
        return None
    return layer, lines

def render_text_safe_circle(im, text, bbox, padding=12):
    font_path = ensure_bengali_font()
    if not font_path:
        raise RuntimeError('Bengali font not found')
    x0, y0, x1, y1 = bbox
    bw = max(1, x1 - x0); bh = max(1, y1 - y0)
    diameter = min(bw, bh)
    max_size = max(8, int(diameter * 0.42))
    min_size = 8
    chosen = None
    for size in range(max_size, min_size - 1, -1):
        result = _fits_circle(text, font_path, size, diameter, padding)
        if result is not None:
            chosen = (size, result[0], result[1])
            break
    if chosen is None:
        size = min_size
        layer, lines, _, _ = _text_layer(text, font_path, size, max(8, diameter - padding * 2))
        chosen = (size, layer, lines)
    _, layer, _ = chosen
    px = int(round(x0 + (bw - layer.width) / 2.0))
    py = int(round(y0 + (bh - layer.height) / 2.0))
    visible = Image.new('RGBA', im.size, (0, 0, 0, 0))
    visible.alpha_composite(layer, (px, py))
    im.paste(visible, (0, 0), visible)

@app.post('/api/render')
async def render(file:UploadFile=File(...),items_json:str=Form(...)):
    try:
        data=await file.read();im=Image.open(io.BytesIO(data)).convert('RGBA');items=json.loads(items_json)
        if not isinstance(items,list):raise ValueError('items_json must be a list')
        draw=ImageDraw.Draw(im)
        for item in items:
            bbox=item.get('bbox') or [];text=(item.get('translation') or '').strip()
            if len(bbox)!=4 or not text:continue
            x0,y0,x1,y1=[int(v) for v in bbox]
            x0=max(0,min(im.width-1,x0));y0=max(0,min(im.height-1,y0));x1=max(x0+1,min(im.width,x1));y1=max(y0+1,min(im.height,y1))
            poly=item.get('polygon') or []
            if poly and len(poly)>=3:
                safe_poly=[]
                for p in poly:
                    if len(p)>=2:safe_poly.append((max(0,min(im.width-1,int(p[0]))),max(0,min(im.height-1,int(p[1])))))
                if len(safe_poly)>=3:draw.polygon(safe_poly,fill='white')
                else:draw.rectangle((x0,y0,x1,y1),fill='white')
            else:draw.rectangle((x0,y0,x1,y1),fill='white')
            render_text_safe_circle(im,text,[x0,y0,x1,y1],padding=max(10,int(min(x1-x0,y1-y0)*0.08)))
        out=io.BytesIO();im.convert('RGB').save(out,format='PNG');out.seek(0)
        return StreamingResponse(out,media_type='image/png',headers={'Content-Disposition':'inline; filename="translated.png"'})
    except HTTPException:raise
    except Exception as e:
        print('RENDER ERROR:',repr(e))
        raise HTTPException(500,f'Render failed: {type(e).__name__}: {e}')

@app.post('/api/auto-translate')
async def auto_translate(req:AutoTranslateRequest):
    out=[]
    for t in req.texts:
        if not t:out.append('');continue
        try:out.append(translator.translate(t) if translator else t)
        except Exception:out.append(t)
    return {'translations':out}

if __name__=='__main__':
    import uvicorn;uvicorn.run(app,host='0.0.0.0',port=8000)
