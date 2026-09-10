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
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def find_fonts():
    candidates = [
        "NotoSansBengali-Bold.ttf", "NotoSansBengali-Regular.ttf",
        "C:/Windows/Fonts/Nirmala.ttf", "C:/Windows/Fonts/NirmalaB.ttf",
        "C:/Windows/Fonts/kalpurush.ttf", "C:/Windows/Fonts/solaimanlipi.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansBengali-Bold.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansBengali-Bold.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansBengali-Regular.ttf",
    ]
    for c in candidates:
        if os.path.exists(c): return c
    return None

FONT_PATH = find_fonts()

class AutoTranslateRequest(BaseModel):
    texts: List[str]

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    with open("index.html", "r", encoding="utf-8") as f: html = f.read()
    html += r'''
<script>
(() => {
  const state = { manual: {}, mode: 'bubble' };
  // Use the page's global lexical currentIndex, not window.currentIndex.
  const key = () => String(typeof currentIndex !== 'undefined' ? currentIndex : -1);
  const items = () => state.manual[key()] || (state.manual[key()] = []);

  function currentImageFile() {
    try {
      if (typeof imageList !== 'undefined' && typeof currentIndex !== 'undefined' && imageList[currentIndex]?.file) {
        return Promise.resolve(imageList[currentIndex].file);
      }
    } catch(e) {}
    const img = document.getElementById('mainImage');
    if (!img || !img.src) return null;
    return fetch(img.src).then(r => r.blob()).then(b => new File([b], 'toon-page.png', {type:b.type || 'image/png'}));
  }

  // Keep the active bubble visible in the image area while translating.
  function scrollImageToBubble(i) {
    const list = items(), it = list[i];
    const stage = document.getElementById('stageView');
    const img = document.getElementById('mainImage');
    if (!it || !stage || !img || !img.naturalWidth || !img.naturalHeight) return;
    const b = it.bbox || [];
    if (b.length < 4) return;
    const rect = img.getBoundingClientRect();
    const stageRect = stage.getBoundingClientRect();
    const cx = rect.left + ((b[0] + b[2]) / 2) * (rect.width / img.naturalWidth);
    const cy = rect.top + ((b[1] + b[3]) / 2) * (rect.height / img.naturalHeight);
    const targetLeft = stage.scrollLeft + (cx - stageRect.left) - stage.clientWidth / 2;
    const targetTop = stage.scrollTop + (cy - stageRect.top) - stage.clientHeight / 2;
    const maxLeft = Math.max(0, stage.scrollWidth - stage.clientWidth);
    const maxTop = Math.max(0, stage.scrollHeight - stage.clientHeight);
    stage.scrollTo({
      left: Math.max(0, Math.min(maxLeft, targetLeft)),
      top: Math.max(0, Math.min(maxTop, targetTop)),
      behavior: 'smooth'
    });
  }

  function addToolbar() {
    const toolbar = document.querySelector('.stage-toolbar');
    if (!toolbar || document.getElementById('bubbleModeBtn')) return;
    const box = document.createElement('div'); box.style.cssText='display:flex;align-items:center;gap:6px;margin-left:auto';
    box.innerHTML='<button id="bubbleModeBtn" class="btn btn-primary" style="padding:7px 11px;font-size:12px">💬 Bubble Select: ON</button><button id="clearBubbleBtn" class="btn" style="padding:7px 11px;font-size:12px">🗑️ Clear Bubbles</button>';
    toolbar.appendChild(box);
    document.getElementById('bubbleModeBtn').onclick=()=>{state.mode=state.mode==='bubble'?'off':'bubble';const b=document.getElementById('bubbleModeBtn');b.textContent=state.mode==='bubble'?'💬 Bubble Select: ON':'🖱️ Bubble Select: OFF';b.classList.toggle('btn-primary',state.mode==='bubble');};
    document.getElementById('clearBubbleBtn').onclick=()=>{state.manual[key()]=[];renderManualSidebar();drawManualOverlay();};
  }

  async function selectBubble(ev) {
    if(state.mode!=='bubble') return;
    const img=document.getElementById('mainImage'); if(!img||!img.naturalWidth)return;
    if(ev.target.closest&&ev.target.closest('.bbox-rect'))return;
    const r=img.getBoundingClientRect();
    const x=Math.round((ev.clientX-r.left)*img.naturalWidth/r.width), y=Math.round((ev.clientY-r.top)*img.naturalHeight/r.height);
    if(x<0||y<0||x>=img.naturalWidth||y>=img.naturalHeight)return;
    try{
      if(window.showSpinner)window.showSpinner('বাবল সিলেক্ট করা হচ্ছে...');
      const file=await currentImageFile(); if(!file)throw new Error('Image unavailable');
      const fd=new FormData();fd.append('file',file);fd.append('x',x);fd.append('y',y);
      const res=await fetch('/api/select-bubble',{method:'POST',body:fd});const data=await res.json();
      if(!res.ok)throw new Error(data.detail||'Bubble not found');
      const exists=items().some(it=>{const a=it.bbox,b=data.bbox;return Math.abs(a[0]-b[0])<12&&Math.abs(a[1]-b[1])<12&&Math.abs(a[2]-b[2])<12&&Math.abs(a[3]-b[3])<12;});
      if(!exists)items().push({id:Date.now(),text:'',conf:1,bbox:data.bbox,polygon:data.polygon||[],translation:'',manual:true});
      renderManualSidebar();drawManualOverlay();
    }catch(e){console.warn(e);alert('এই জায়গায় পূর্ণ বাবল পাওয়া যায়নি। বাবলের সাদা/ভেতরের অংশে আবার ক্লিক করুন।');}
    finally{if(window.hideSpinner)window.hideSpinner();}
  }

  function drawManualOverlay(){
    const svg=document.getElementById('overlaySvg'),img=document.getElementById('mainImage');if(!svg||!img||!img.naturalWidth)return;
    svg.setAttribute('viewBox',`0 0 ${img.naturalWidth} ${img.naturalHeight}`);svg.innerHTML='';
    items().forEach((it,i)=>{const[x0,y0,x1,y1]=it.bbox,g=document.createElementNS('http://www.w3.org/2000/svg','g'),rect=document.createElementNS('http://www.w3.org/2000/svg','rect');rect.setAttribute('x',x0);rect.setAttribute('y',y0);rect.setAttribute('width',Math.max(1,x1-x0));rect.setAttribute('height',Math.max(1,y1-y0));rect.setAttribute('class','bbox-rect active');rect.style.fill='rgba(16,185,129,.10)';rect.style.stroke='#10b981';rect.addEventListener('click',e=>{e.stopPropagation();focusCard(i);});g.appendChild(rect);svg.appendChild(g);});
  }

  function focusCard(i){const el=document.getElementById('bubble-card-'+i);if(el){el.scrollIntoView({behavior:'smooth',block:'center'});const inp=el.querySelector('textarea');if(inp){inp.focus();setTimeout(()=>scrollImageToBubble(i),80);}}}

  function renderManualSidebar(){
    const wrap=document.getElementById('sidebarContent'),count=document.getElementById('detectionCount');if(!wrap)return;const list=items();if(count)count.textContent=list.length;
    if(!list.length){wrap.innerHTML='<div class="empty-state"><div class="empty-icon">💬</div><p>Bubble Select চালু রেখে ছবির প্রতিটি পূর্ণ বাবলের ভিতরে একবার ক্লিক করুন। অসম্পূর্ণ বাবল ক্লিক করবেন না।</p></div>';return;}
    wrap.innerHTML='';list.forEach((it,i)=>{const card=document.createElement('div');card.className='item-card';card.id='bubble-card-'+i;card.innerHTML=`<div class="item-header"><span class="item-badge">Bubble ${i+1}</span><div class="item-actions"><button class="btn-icon" title="এই বাবল মুছুন">🗑️</button></div></div><div class="original-text">Manual bubble selection • ${it.bbox[2]-it.bbox[0]} × ${it.bbox[3]-it.bbox[1]} px</div><div class="input-wrapper"><textarea class="translation-input" placeholder="এখানে বাংলা অনুবাদ লিখুন...">${it.translation||''}</textarea></div><div class="input-tip"><span>Enter = পরের বাবল</span><span>Render করলে লেখা বাবলের মধ্যে Auto-Fit হবে</span></div>`;const ta=card.querySelector('textarea');ta.addEventListener('focus',()=>{setTimeout(()=>scrollImageToBubble(i),80);});ta.addEventListener('click',()=>{setTimeout(()=>scrollImageToBubble(i),50);});ta.addEventListener('input',()=>{it.translation=ta.value;});ta.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();const n=wrap.querySelectorAll('textarea')[i+1];if(n){n.focus();setTimeout(()=>scrollImageToBubble(i+1),80);}}});card.querySelector('.btn-icon').onclick=()=>{list.splice(i,1);renderManualSidebar();drawManualOverlay();};wrap.appendChild(card);});
  }

  async function renderManual(){
    const list=items().filter(it=>it.translation&&it.translation.trim());if(!list.length){alert('কমপক্ষে একটি বাবলের বাংলা অনুবাদ লিখুন।');return;}
    try{
      if(window.showSpinner)window.showSpinner('বাবলের মধ্যে অনুবাদ বসানো হচ্ছে...');
      const file=await currentImageFile();if(!file)throw new Error('Image unavailable');
      const fd=new FormData();fd.append('file',file);fd.append('items_json',JSON.stringify(list));
      const res=await fetch('/api/render',{method:'POST',body:fd});if(!res.ok)throw new Error(await res.text());
      const blob=await res.blob(),url=URL.createObjectURL(blob);
      window.currentRenderedUrl=url;
      try{if(typeof imageList!=='undefined'&&typeof currentIndex!=='undefined'&&imageList[currentIndex])imageList[currentIndex].renderedUrl=url;}catch(e){}
      const img=document.getElementById('mainImage');
      if(typeof activeView!=='undefined')activeView='rendered';
      document.getElementById('btnOriginal')?.classList.remove('active');document.getElementById('btnRendered')?.classList.add('active');
      img.src=url;if(img.onload){};
    }catch(e){console.error(e);alert('Render করা যায়নি: '+e.message);}
    finally{if(window.hideSpinner)window.hideSpinner();}
  }

  function install(){
    addToolbar();const img=document.getElementById('mainImage');if(img&&!img.dataset.bubbleBound){img.dataset.bubbleBound='1';img.addEventListener('click',selectBubble);}
    const renderBtn=[...document.querySelectorAll('button')].find(b=>b.textContent.includes('রেন্ডার কার্টুন')) || [...document.querySelectorAll('button')].find(b=>b.textContent.includes('রেন্ডার'));
    if(renderBtn&&!renderBtn.dataset.manualRender){renderBtn.dataset.manualRender='1';renderBtn.addEventListener('click',e=>{if(items().length){e.stopImmediatePropagation();renderManual();}},true);}
    const observer=new MutationObserver(()=>{addToolbar();const im=document.getElementById('mainImage');if(im&&!im.dataset.bubbleBound){im.dataset.bubbleBound='1';im.addEventListener('click',selectBubble);}});observer.observe(document.body,{childList:true,subtree:true});renderManualSidebar();drawManualOverlay();
  }
  window.addEventListener('load',()=>setTimeout(install,250));
  window.toonBubbleManual={renderManual,renderManualSidebar,drawManualOverlay,scrollImageToBubble};
})();
</script>
'''
    return HTMLResponse(content=html)

def bbox_iou(a,b):
    ax0,ay0,ax1,ay1=a;bx0,by0,bx1,by1=b;ix0,iy0=max(ax0,bx0),max(ay0,by0);ix1,iy1=min(ax1,bx1),min(ay1,by1);iw,ih=max(0,ix1-ix0),max(0,iy1-iy0);inter=iw*ih
    if inter<=0:return 0.0
    area_a=max(0,ax1-ax0)*max(0,ay1-ay0);area_b=max(0,bx1-bx0)*max(0,by1-by0);return inter/float(area_a+area_b-inter+1e-6)

def text_similarity(a,b):
    from difflib import SequenceMatcher
    a=''.join(ch.lower() for ch in a if ch.isalnum());b=''.join(ch.lower() for ch in b if ch.isalnum())
    if not a or not b:return 0.0
    return SequenceMatcher(None,a,b).ratio()

def clean_ocr_text(text):return re.sub(r'\s+',' ',(text or '')).strip()

def looks_like_real_english_text(text,conf,bbox,image_w,image_h):
    text=clean_ocr_text(text)
    if not text or conf<0.22:return False
    allowed=sum(1 for ch in text if ch.isascii() and (ch.isalnum() or ch in " .,!?'-:;()&%+$#/@"));visible=sum(1 for ch in text if not ch.isspace())
    if visible==0 or allowed/float(visible)<0.80:return False
    if len(text)>120:return False
    compact=re.sub(r'\s+','',text.lower())
    if len(compact)>=8 and len(set(compact))<=2:return False
    x0,y0,x1,y1=bbox;bw,bh=max(1,x1-x0),max(1,y1-y0)
    if bw>image_w*0.75 and bh>image_h*0.30:return False
    if bw*bh>image_w*image_h*0.20:return False
    if bh>bw*8 and len(compact)<12:return False
    return True

def preprocess_variants(tile):
    variants=[tile];gray=cv2.cvtColor(tile,cv2.COLOR_BGR2GRAY);up=cv2.resize(gray,None,fx=2.0,fy=2.0,interpolation=cv2.INTER_CUBIC);clahe=cv2.createCLAHE(clipLimit=2.0,tileGridSize=(8,8));contrast=clahe.apply(up);variants.append(cv2.cvtColor(contrast,cv2.COLOR_GRAY2BGR));blur=cv2.GaussianBlur(contrast,(0,0),1.0);sharp=cv2.addWeighted(contrast,1.35,blur,-0.35,0);variants.append(cv2.cvtColor(sharp,cv2.COLOR_GRAY2BGR));return variants

def add_detection(results,bbox,text,conf,tile_y0,scale_x,scale_y,image_w,image_h):
    text=clean_ocr_text(text);pts=np.asarray(bbox,dtype=np.float32)
    if pts.size==0:return
    x0=int(round(float(np.min(pts[:,0]))/scale_x));y0=int(round(float(np.min(pts[:,1]))/scale_y+tile_y0));x1=int(round(float(np.max(pts[:,0]))/scale_x));y1=int(round(float(np.max(pts[:,1]))/scale_y+tile_y0));x0=max(0,min(image_w-1,x0));y0=max(0,min(image_h-1,y0));x1=max(0,min(image_w,x1));y1=max(0,min(image_h,y1));bbox_out=[x0,y0,x1,y1]
    if not looks_like_real_english_text(text,float(conf),bbox_out,image_w,image_h):return
    results.append({"text":text,"conf":float(conf),"bbox":bbox_out})

def merge_detections(results):
    results=sorted(results,key=lambda d:d['conf'],reverse=True);kept=[]
    for item in results:
        duplicate_index=None
        for i,existing in enumerate(kept):
            iou=bbox_iou(item['bbox'],existing['bbox']);sim=text_similarity(item['text'],existing['text'])
            if iou>=0.55 or (iou>=0.25 and sim>=0.65) or (sim>=0.90 and iou>=0.10):
                duplicate_index=i;break
        if duplicate_index is None:kept.append(item)
    return kept

@app.post("/api/detect")
async def detect(file: UploadFile=File(...)):
    data=await file.read()
    img=np.frombuffer(data,np.uint8);img=cv2.imdecode(img,cv2.IMREAD_COLOR)
    if img is None: raise HTTPException(400,"Invalid image")
    h,w=img.shape[:2];reader=get_ocr_reader()
    if reader is None:return {"detections":[]}
    results=[]
    tile_h=1500;overlap=250;ys=[0] if h<=tile_h else list(range(0,h,tile_h-overlap))
    if ys and ys[-1]+tile_h<h:ys.append(h-tile_h)
    for y0 in ys:
        y1=min(h,y0+tile_h);tile=img[y0:y1]
        for variant in preprocess_variants(tile):
            scale_x=variant.shape[1]/tile.shape[1];scale_y=variant.shape[0]/tile.shape[0]
            try: detections=reader.readtext(variant,paragraph=False,detail=1,text_threshold=0.35,low_text=0.25,link_threshold=0.30,mag_ratio=1.0,canvas_size=2500,slope_ths=0.45,ycenter_ths=0.6,height_ths=0.6,width_ths=0.6,add_margin=0.05,decoder="greedy")
            except Exception as e: print("OCR Error:",e);continue
            for pts,text,conf in detections:add_detection(results,pts,text,conf,y0,scale_x,scale_y,w,h)
    merged=merge_detections(results)
    for i,d in enumerate(merged):d['id']=i
    return {"detections":merged}

@app.post("/api/select-bubble")
async def select_bubble(file: UploadFile=File(...),x:int=Form(...),y:int=Form(...)):
    data=await file.read();arr=np.frombuffer(data,np.uint8);img=cv2.imdecode(arr,cv2.IMREAD_COLOR)
    if img is None:raise HTTPException(400,"Invalid image")
    h,w=img.shape[:2]
    if not(0<=x<w and 0<=y<h):raise HTTPException(400,"Point outside image")
    gray=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
    mask=cv2.inRange(gray,245,255)
    n,labels,stats,cent=cv2.connectedComponentsWithStats(mask,8)
    candidates=[]
    for i in range(1,n):
        x0,y0,bw,bh,area=stats[i]
        if area<500 or bw<30 or bh<30:continue
        if not(x0<=x<x0+bw and y0<=y<y0+bh):continue
        fill=area/float(max(1,bw*bh))
        if fill<0.35:continue
        if bw>0.85*w or bh>0.85*h:continue
        dist=abs((x0+bw/2)-x)+abs((y0+bh/2)-y)
        candidates.append((dist,area,[int(x0),int(y0),int(x0+bw),int(y0+bh)]))
    if not candidates:raise HTTPException(404,"Full speech bubble not found")
    _,area,bbox=min(candidates,key=lambda t:t[0])
    x0,y0,x1,y1=bbox;roi=gray[y0:y1,x0:x1];white=cv2.inRange(roi,245,255)
    contours,_=cv2.findContours(white,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    poly=[]
    if contours:
        c=max(contours,key=cv2.contourArea);eps=0.01*cv2.arcLength(c,True);p=cv2.approxPolyDP(c,eps,True).reshape(-1,2);poly=[[int(px+x0),int(py+y0)] for px,py in p]
    return {"bbox":bbox,"polygon":poly,"area":area}

def wrap_text(text,font,max_width):
    words=text.split();lines=[];cur=""
    for word in words:
        test=word if not cur else cur+" "+word
        if font.getlength(test)<=max_width:cur=test
        else:
            if cur:lines.append(cur)
            cur=word
    if cur:lines.append(cur)
    return lines or [""]

def fit_font(draw,text,max_w,max_h):
    if not FONT_PATH:return ImageFont.load_default()
    for size in range(max(10,int(min(max_h,max_w)*0.08)),7,-1):
        f=ImageFont.truetype(FONT_PATH,size)
        lines=wrap_text(text,f,max_w);bbox=draw.multiline_textbbox((0,0),"\n".join(lines),font=f,spacing=max(2,size//5),align='center')
        if bbox[2]-bbox[0]<=max_w and bbox[3]-bbox[1]<=max_h:return f
    return ImageFont.truetype(FONT_PATH,8)

@app.post("/api/render")
async def render(file:UploadFile=File(...),items_json:str=Form(...)):
    data=await file.read();im=Image.open(io.BytesIO(data)).convert('RGB');items=json.loads(items_json);draw=ImageDraw.Draw(im)
    for item in items:
        bbox=item.get('bbox') or [];text=(item.get('translation') or '').strip()
        if len(bbox)!=4 or not text:continue
        x0,y0,x1,y1=[int(v) for v in bbox]
        poly=item.get('polygon') or []
        if poly and len(poly)>=3:draw.polygon([tuple(p) for p in poly],fill='white')
        else:draw.rectangle((x0,y0,x1,y1),fill='white')
        max_w=max(20,x1-x0-20);max_h=max(20,y1-y0-20);font=fit_font(draw,text,max_w,max_h);lines=wrap_text(text,font,max_w);spacing=max(2,int(getattr(font,'size',12)*0.2));bb=draw.multiline_textbbox((0,0),'\n'.join(lines),font=font,spacing=spacing,align='center');tw,th=bb[2]-bb[0],bb[3]-bb[1];tx=x0+(x1-x0-tw)/2;ty=y0+(y1-y0-th)/2;draw.multiline_text((tx,ty),'\n'.join(lines),font=font,fill='black',spacing=spacing,align='center')
    out=io.BytesIO();im.save(out,format='PNG');out.seek(0);return StreamingResponse(out,media_type='image/png',headers={'Content-Disposition':'attachment; filename="translated.png"'})

@app.post("/api/auto-translate")
async def auto_translate(req:AutoTranslateRequest):
    out=[]
    for t in req.texts:
        if not t:out.append("");continue
        try:
            if translator:out.append(translator.translate(t))
            else:out.append(t)
        except Exception:out.append(t)
    return {"translations":out}
'''
