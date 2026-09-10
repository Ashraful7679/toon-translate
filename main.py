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

  function focusCard(i){const el=document.getElementById('bubble-card-'+i);if(el){el.scrollIntoView({behavior:'smooth',block:'center'});const inp=el.querySelector('textarea');if(inp)inp.focus();}}

  function renderManualSidebar(){
    const wrap=document.getElementById('sidebarContent'),count=document.getElementById('detectionCount');if(!wrap)return;const list=items();if(count)count.textContent=list.length;
    if(!list.length){wrap.innerHTML='<div class="empty-state"><div class="empty-icon">💬</div><p>Bubble Select চালু রেখে ছবির প্রতিটি পূর্ণ বাবলের ভিতরে একবার ক্লিক করুন। অসম্পূর্ণ বাবল ক্লিক করবেন না।</p></div>';return;}
    wrap.innerHTML='';list.forEach((it,i)=>{const card=document.createElement('div');card.className='item-card';card.id='bubble-card-'+i;card.innerHTML=`<div class="item-header"><span class="item-badge">Bubble ${i+1}</span><div class="item-actions"><button class="btn-icon" title="এই বাবল মুছুন">🗑️</button></div></div><div class="original-text">Manual bubble selection • ${it.bbox[2]-it.bbox[0]} × ${it.bbox[3]-it.bbox[1]} px</div><div class="input-wrapper"><textarea class="translation-input" placeholder="এখানে বাংলা অনুবাদ লিখুন...">${it.translation||''}</textarea></div><div class="input-tip"><span>Enter = পরের বাবল</span><span>Render করলে লেখা বাবলের মধ্যে Auto-Fit হবে</span></div>`;const ta=card.querySelector('textarea');ta.addEventListener('input',()=>{it.translation=ta.value;});ta.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();const n=wrap.querySelectorAll('textarea')[i+1];if(n)n.focus();}});card.querySelector('.btn-icon').onclick=()=>{list.splice(i,1);renderManualSidebar();drawManualOverlay();};wrap.appendChild(card);});
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
      // Keep the rendered URL in the same image object used by switchView/downloadImage.
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
    const renderBtn=[...document.querySelectorAll('button')].find(b=>b.textContent.includes('রেন্ডার কার্টুন'));
    if(renderBtn&&!renderBtn.dataset.manualRender){renderBtn.dataset.manualRender='1';renderBtn.addEventListener('click',e=>{if(items().length){e.stopImmediatePropagation();renderManual();}},true);}
    const observer=new MutationObserver(()=>{addToolbar();const im=document.getElementById('mainImage');if(im&&!im.dataset.bubbleBound){im.dataset.bubbleBound='1';im.addEventListener('click',selectBubble);}});observer.observe(document.body,{childList:true,subtree:true});renderManualSidebar();drawManualOverlay();
  }
  window.addEventListener('load',()=>setTimeout(install,250));
  window.toonBubbleManual={renderManual,renderManualSidebar,drawManualOverlay};
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
            if iou>=0.30 or (sim>=0.78 and iou>=0.10):duplicate_index=i;break
        if duplicate_index is None:kept.append(item)
        elif item['conf']>kept[duplicate_index]['conf']:kept[duplicate_index]=item
    return kept

def detect_text_with_easyocr(img,reader):
    h,w=img.shape[:2];raw=[];max_tile_h=1500;overlap=250;tiles=[];y=0
    while y<h:
        y1=min(h,y+max_tile_h);tiles.append((y,y1))
        if y1>=h:break
        y=y1-overlap
    for tile_y0,tile_y1 in tiles:
        tile=img[tile_y0:tile_y1,0:w];tile_h,tile_w=tile.shape[:2]
        for variant_index,variant in enumerate(preprocess_variants(tile)):
            vh,vw=variant.shape[:2];scale_x=vw/float(tile_w);scale_y=vh/float(tile_h)
            try:results=reader.readtext(variant,paragraph=False,detail=1,text_threshold=0.35,low_text=0.25,link_threshold=0.30,mag_ratio=1.0,canvas_size=2500,slope_ths=0.45,ycenter_ths=0.6,height_ths=0.6,width_ths=0.6,add_margin=0.05,decoder='greedy')
            except Exception as err:print(f'EasyOCR error tile={tile_y0}:{tile_y1}, variant={variant_index}: {err}');continue
            for bbox,text,conf in results:add_detection(raw,bbox,text,conf,tile_y0,scale_x,scale_y,w,h)
    return merge_detections(raw)

@app.post('/api/detect')
async def detect(file:UploadFile=File(...)):
    if not file:raise HTTPException(status_code=400,detail='No image provided')
    contents=await file.read();img=cv2.imdecode(np.frombuffer(contents,np.uint8),cv2.IMREAD_COLOR)
    if img is None:raise HTTPException(status_code=400,detail='Invalid image file')
    h,w=img.shape[:2];print(f'OCR image received: {w}x{h}');reader=get_ocr_reader()
    if reader is None:raise HTTPException(status_code=500,detail='EasyOCR could not be initialized')
    try:detections=detect_text_with_easyocr(img,reader);print(f'EasyOCR final text detections: {len(detections)}')
    except Exception as err:print('OCR Error:',err);raise HTTPException(status_code=500,detail=f'OCR failed: {err}')
    detections.sort(key=lambda d:(d['bbox'][1],d['bbox'][0]))
    for i,d in enumerate(detections):d['id']=i
    return {'detections':detections,'width':w,'height':h}

@app.post('/api/select-bubble')
async def select_bubble(file:UploadFile=File(...),x:int=Form(...),y:int=Form(...)):
    contents=await file.read();img=cv2.imdecode(np.frombuffer(contents,np.uint8),cv2.IMREAD_COLOR)
    if img is None:raise HTTPException(status_code=400,detail='Invalid image')
    h,w=img.shape[:2];x=max(0,min(w-1,int(x)));y=max(0,min(h-1,int(y)));gray=cv2.cvtColor(img,cv2.COLOR_BGR2GRAY);gray=cv2.GaussianBlur(gray,(3,3),0)
    best=None;best_val=-1
    for radius in (8,16,28):
        yy0,yy1=max(0,y-radius),min(h,y+radius+1);xx0,xx1=max(0,x-radius),min(w,x+radius+1);patch=gray[yy0:yy1,xx0:xx1];loc=np.argwhere(patch>=205)
        if loc.size:
            for py,px in loc:
                val=int(patch[py,px]);dist=(py+yy0-y)**2+(px+xx0-x)**2;score=val-dist*0.15
                if score>best_val:best_val=score;best=(px+xx0,py+yy0)
            if best:break
    if best is None:best=(x,y)
    sx,sy=best;flood=np.zeros((h+2,w+2),np.uint8);work=gray.copy();lo,up=25,25;flags=4|(255<<8)|cv2.FLOODFILL_FIXED_RANGE
    try:cv2.floodFill(work,flood,(int(sx),int(sy)),255,(lo,lo,lo),(up,up,up),flags)
    except Exception as e:raise HTTPException(status_code=400,detail=f'Bubble selection failed: {e}')
    mask=(flood[1:-1,1:-1]>0).astype(np.uint8)*255;contours,_=cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    if not contours:raise HTTPException(status_code=404,detail='No bubble found')
    contour=max(contours,key=cv2.contourArea);area=float(cv2.contourArea(contour))
    if area<max(200.0,w*h*0.00015) or area>w*h*0.35:raise HTTPException(status_code=404,detail='No complete speech bubble found at this point')
    bx,by,bw,bh=cv2.boundingRect(contour);pad=max(3,int(min(bw,bh)*0.02));bx=max(0,bx-pad);by=max(0,by-pad);bw=min(w-bx,bw+2*pad);bh=min(h-by,bh+2*pad);eps=max(2.0,min(bw,bh)*0.01);approx=cv2.approxPolyDP(contour,eps,True).reshape(-1,2).tolist()
    if len(approx)<4:approx=cv2.boxPoints(((bx+bw/2,by+bh/2),(bw,bh),0)).astype(int).tolist()
    return {'bbox':[bx,by,bx+bw,by+bh],'polygon':approx,'area':area}

@app.post('/api/auto-translate')
async def auto_translate(req:AutoTranslateRequest):
    results=[]
    for text in req.texts:
        if not text.strip():results.append('');continue
        translated=''
        if translator:
            try:translated=translator.translate(text)
            except Exception as e:print('Translation Error:',e)
        if not translated:
            try:
                import requests;r=requests.get('https://api.mymemory.translated.net/get',params={'q':text,'langpair':'en|bn'},timeout=6);translated=r.json().get('responseData',{}).get('translatedText','')
            except Exception:translated=''
        results.append(translated)
    return {'translations':results}

@app.post('/api/render')
async def render_image(file:UploadFile=File(...),items_json:str=Form(...)):
    contents=await file.read();img_cv=cv2.imdecode(np.frombuffer(contents,np.uint8),cv2.IMREAD_COLOR)
    if img_cv is None:raise HTTPException(status_code=400,detail='Invalid image')
    items=json.loads(items_json)
    for item in items:
        bbox=item.get('bbox');translation=item.get('translation','').strip()
        if not bbox or not translation:continue
        polygon=item.get('polygon') or []
        if polygon and len(polygon)>=3:
            pts=np.asarray(polygon,dtype=np.int32).reshape(-1,1,2);cv2.fillPoly(img_cv,[pts],(255,255,255))
        else:
            x0,y0,x1,y1=map(int,bbox);pad=4;cv2.rectangle(img_cv,(max(0,x0-pad),max(0,y0-pad)),(min(img_cv.shape[1],x1+pad),min(img_cv.shape[0],y1+pad)),(255,255,255),-1)
    img_pil=Image.fromarray(cv2.cvtColor(img_cv,cv2.COLOR_BGR2RGB));draw=ImageDraw.Draw(img_pil)
    for item in items:
        bbox=item.get('bbox');bangla_text=item.get('translation','').strip()
        if not bbox or not bangla_text:continue
        x0,y0,x1,y1=map(int,bbox);W=max(10,x1-x0);H=max(10,y1-y0);fontsize=min(96,max(12,int(H*0.34)));font=None;lines=[]
        while fontsize>=10:
            try:font=ImageFont.truetype(FONT_PATH,fontsize) if FONT_PATH else ImageFont.load_default()
            except Exception:font=ImageFont.load_default()
            words=bangla_text.split();lines=[];cur=''
            for word in words:
                test=cur+' '+word if cur else word
                try:tw=draw.textbbox((0,0),test,font=font)[2]
                except Exception:tw=len(test)*(fontsize*0.6)
                if tw<=W*0.92:cur=test
                else:
                    if cur:lines.append(cur)
                    cur=word
            if cur:lines.append(cur)
            line_height=fontsize*1.15;total_h=len(lines)*line_height
            if total_h<=H*0.86 or fontsize<=10:break
            fontsize-=2
        line_height=fontsize*1.15;total_h=len(lines)*line_height;curr_y=y0+(H-total_h)/2
        for line in lines:
            try:tw=draw.textbbox((0,0),line,font=font)[2]
            except Exception:tw=len(line)*(fontsize*0.6)
            curr_x=x0+max(0,(W-tw)/2);draw.text((curr_x,curr_y),line,font=font,fill=(0,0,0));curr_y+=line_height
    final_cv=cv2.cvtColor(np.array(img_pil),cv2.COLOR_RGB2BGR);_,encoded_img=cv2.imencode('.png',final_cv)
    return StreamingResponse(io.BytesIO(encoded_img.tobytes()),media_type='image/png')

if __name__=='__main__':
    import uvicorn;uvicorn.run(app,host='0.0.0.0',port=8000)
