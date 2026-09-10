import sys, importlib.abc, importlib.machinery

_TARGET = 'main'

OLD_FIT = '''def fit_font(draw,text,max_w,max_h):
    if not FONT_PATH:return ImageFont.load_default()
    for size in range(max(10,int(min(max_h,max_w)*0.10)),7,-1):
        f=ImageFont.truetype(FONT_PATH,size)
        lines=wrap_text(text,f,max_w)
        spacing=max(2,size//5)
        bbox=draw.multiline_textbbox((0,0),'\\n'.join(lines),font=f,spacing=spacing,align='center')
        if bbox[2]-bbox[0]<=max_w and bbox[3]-bbox[1]<=max_h:return f
    return ImageFont.truetype(FONT_PATH,8)
'''

NEW_FIT = '''def _text_rect_inside_polygon(x0,y0,x1,y1,poly,margin=3):
    if not poly or len(poly)<3:
        return True
    pts=np.asarray(poly,dtype=np.int32).reshape((-1,1,2))
    if cv2.contourArea(pts)<10:
        return True
    m=float(max(0,margin))
    if x1-x0 <= 2*m or y1-y0 <= 2*m:
        return False
    samples=[]
    for t in np.linspace(0,1,9):
        samples.extend([
            (x0+m+(x1-x0-2*m)*float(t), y0+m),
            (x0+m+(x1-x0-2*m)*float(t), y1-m),
            (x0+m, y0+m+(y1-y0-2*m)*float(t)),
            (x1-m, y0+m+(y1-y0-2*m)*float(t)),
        ])
    return all(cv2.pointPolygonTest(pts,(float(x),float(y)),False)>=0 for x,y in samples)

def fit_font(draw,text,max_w,max_h,polygon=None,region=None):
    if not FONT_PATH:return ImageFont.load_default()
    start=max(8,int(min(max_h,max_w)*0.08))
    rx0,ry0,rx1,ry1=region if region else (0,0,max_w,max_h)
    for size in range(start,7,-1):
        f=ImageFont.truetype(FONT_PATH,size)
        lines=wrap_text(text,f,max_w)
        spacing=max(2,size//5)
        joined='\\n'.join(lines)
        bbox=draw.multiline_textbbox((0,0),joined,font=f,spacing=spacing,align='center')
        tw,th=bbox[2]-bbox[0],bbox[3]-bbox[1]
        if tw>max_w or th>max_h:
            continue
        tx=rx0+(rx1-rx0-tw)/2
        ty=ry0+(ry1-ry0-th)/2
        if _text_rect_inside_polygon(tx,ty,tx+tw,ty+th,polygon,margin=3):
            return f
    return ImageFont.truetype(FONT_PATH,8)
'''

OLD_CALL = 'font=fit_font(draw,text,max_w,max_h)'
NEW_CALL = 'font=fit_font(draw,text,max_w,max_h,poly,(x0,y0,x1,y1))'
OLD_CANDIDATE = 'candidates.append((dist,area,[int(x0),int(y0),int(x0+bw),int(y0+bh)]))'
NEW_CANDIDATE = 'candidates.append((dist,area,i,[int(x0),int(y0),int(x0+bw),int(y0+bh)]))'
OLD_UNPACK = '_,_,bbox=min(candidates,key=lambda z:z[0])'
NEW_UNPACK = '_,_,label_idx,bbox=min(candidates,key=lambda z:z[0])'
OLD_ROI = "roi=gray[y0:y1,x0:x1]\n    _,th=cv2.threshold(roi,245,255,cv2.THRESH_BINARY);contours,_=cv2.findContours(th,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)"
NEW_ROI = "component=(labels[y0:y1,x0:x1]==label_idx).astype(np.uint8)*255\n    contours,_=cv2.findContours(component,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)"

OLD_FOCUS = "function focusCard(i){const el=document.getElementById('bubble-card-'+i);if(el){el.scrollIntoView({behavior:'smooth',block:'center'});const inp=el.querySelector('textarea');if(inp)inp.focus();}}"
NEW_FOCUS = "function scrollToBubbleBBox(b){const stage=document.getElementById('stageView'),img=document.getElementById('mainImage');if(!stage||!img||!img.naturalWidth||!b||b.length<4)return;const r=img.getBoundingClientRect(),sr=stage.getBoundingClientRect(),cx=r.left+(b[0]+b[2])/2*(r.width/img.naturalWidth),cy=r.top+(b[1]+b[3])/2*(r.height/img.naturalHeight),left=stage.scrollLeft+cx-sr.left-stage.clientWidth/2,top=stage.scrollTop+cy-sr.top-stage.clientHeight/2;stage.scrollTo({left:Math.max(0,Math.min(stage.scrollWidth-stage.clientWidth,left)),top:Math.max(0,Math.min(stage.scrollHeight-stage.clientHeight,top)),behavior:'smooth'});} function focusCard(i){const el=document.getElementById('bubble-card-'+i);if(el){el.scrollIntoView({behavior:'smooth',block:'center'});const inp=el.querySelector('textarea');if(inp){inp.focus({preventScroll:true});setTimeout(()=>scrollToBubbleBBox(items()[i]?.bbox),100);}}}"

OLD_TEXTAREA_BIND = "function bindManualTextarea(card,i){const ta=card.querySelector('textarea');if(!ta)return;ta.addEventListener('focus',()=>scrollStageToBubble(items()[i]?.bbox));ta.addEventListener('click',()=>scrollStageToBubble(items()[i]?.bbox));ta.addEventListener('input',()=>{items()[i].translation=ta.value;});ta.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();const n=document.querySelector('#sidebarContent textarea[data-bubble-index=\"'+(i+1)+'\"]');if(n)n.focus();}});}"
NEW_TEXTAREA_BIND = "function bindManualTextarea(card,i){const ta=card.querySelector('textarea[data-bubble-index=\"'+i+'\"]');if(!ta)return;ta.addEventListener('focus',()=>scrollStageToBubble(items()[i]?.bbox));ta.addEventListener('click',()=>scrollStageToBubble(items()[i]?.bbox));ta.addEventListener('input',()=>{items()[i].translation=ta.value;items()[i].bijoy='';const out=card.querySelector('.bijoy-output');if(out)out.value='';});ta.addEventListener('compositionstart',()=>ta.dataset.composing='1');ta.addEventListener('compositionend',()=>{ta.dataset.composing='0';items()[i].translation=ta.value.normalize('NFC');});ta.addEventListener('keydown',e=>{if(e.isComposing||ta.dataset.composing==='1')return;if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();const n=document.querySelector('#sidebarContent textarea[data-bubble-index=\"'+(i+1)+'\"]');if(n)n.focus();}});}"

OLD_SIDEBAR = "function renderManualSidebar(){const wrap=document.getElementById('sidebarContent'),count=document.getElementById('detectionCount');if(!wrap)return;const list=items();if(count)count.textContent=list.length;if(!list.length){wrap.innerHTML='<div class=\"empty-state\"><div class=\"empty-icon\">💬</div><p>Bubble Select চালু রেখে ছবির প্রতিটি পূর্ণ বাবলের ভিতরে একবার ক্লিক করুন।</p></div>';return;}wrap.innerHTML='';list.forEach((it,i)=>{const card=document.createElement('div');card.className='item-card';card.id='bubble-card-'+i;card.innerHTML=`<div class=\"item-header\"><span class=\"item-badge\">Bubble ${i+1}</span><div class=\"item-actions\"><button class=\"btn-icon\" title=\"এই বাবল মুছুন\">🗑️</button></div></div><div class=\"original-text\">Manual bubble • ${it.bbox[2]-it.bbox[0]} × ${it.bbox[3]-it.bbox[1]} px</div><div class=\"input-wrapper\"><textarea class=\"translation-input\" data-bubble-index=\"${i}\" placeholder=\"এখানে বাংলা অনুবাদ লিখুন...\">${it.translation||''}</textarea></div><div class=\"input-tip\"><span>Enter = পরের বাবল</span><span>Polygon Auto-Fit</span></div>`;card.querySelector('.btn-icon').onclick=()=>{list.splice(i,1);renderManualSidebar();drawManualOverlay();};wrap.appendChild(card);bindManualTextarea(card,i);});}"
NEW_SIDEBAR = "function renderManualSidebar(){const wrap=document.getElementById('sidebarContent'),count=document.getElementById('detectionCount');if(!wrap)return;const list=items();if(count)count.textContent=list.length;if(!list.length){wrap.innerHTML='<div class=\"empty-state\"><div class=\"empty-icon\">💬</div><p>Bubble Select চালু রেখে ছবির প্রতিটি পূর্ণ বাবলের ভিতরে একবার ক্লিক করুন।</p></div>';return;}wrap.innerHTML='';list.forEach((it,i)=>{const card=document.createElement('div');card.className='item-card';card.id='bubble-card-'+i;card.innerHTML=`<div class=\"item-header\"><span class=\"item-badge\">Bubble ${i+1}</span><div class=\"item-actions\"><button class=\"btn-icon\" title=\"এই বাবল মুছুন\">🗑️</button></div></div><div class=\"original-text\">Avro/Unicode input • ${it.bbox[2]-it.bbox[0]} × ${it.bbox[3]-it.bbox[1]} px</div><div class=\"input-wrapper\"><label style=\"font-size:11px;color:#94a3b8;display:block;margin-bottom:4px\">Avro / Unicode</label><textarea class=\"translation-input\" data-bubble-index=\"${i}\" placeholder=\"এখানে বাংলা লিখুন...\">${it.translation||''}</textarea><label style=\"font-size:11px;color:#94a3b8;display:block;margin:8px 0 4px\">Bijoy (SutonnyMJ)</label><textarea class=\"translation-input bijoy-output\" data-bijoy-index=\"${i}\" readonly placeholder=\"Render চাপলে এখানে Bijoy text আসবে...\" style=\"font-family:'SutonnyMJ','SutonnyMJ Regular',monospace;color:#fbbf24;min-height:42px\">${it.bijoy||''}</textarea></div><div class=\"input-tip\"><span>Render → Avro-to-Bijoy → Image</span><span>Polygon Auto-Fit</span></div>`;card.querySelector('.btn-icon').onclick=()=>{list.splice(i,1);renderManualSidebar();drawManualOverlay();};wrap.appendChild(card);bindManualTextarea(card,i);});}"

OLD_RENDER = "async function renderManual(){const list=items().filter(it=>it.translation&&it.translation.trim());if(!list.length){alert('কমপক্ষে একটি বাবলের বাংলা অনুবাদ লিখুন।');return;}try{if(window.showSpinner)window.showSpinner('বাবলের মধ্যে অনুবাদ বসানো হচ্ছে...');const file=await currentImageFile();if(!file)throw new Error('Image unavailable');const fd=new FormData();fd.append('file',file);fd.append('items_json',JSON.stringify(list));const res=await fetch('/api/render',{method:'POST',body:fd});if(!res.ok)throw new Error(await res.text());const blob=await res.blob(),url=URL.createObjectURL(blob);try{if(typeof imageList!=='undefined'&&typeof currentIndex!=='undefined'&&imageList[currentIndex])imageList[currentIndex].renderedUrl=url;}catch(e){}const img=document.getElementById('mainImage');if(typeof activeView!=='undefined')activeView='rendered';document.getElementById('btnOriginal')?.classList.remove('active');document.getElementById('btnRendered')?.classList.add('active');img.src=url;img.onload=()=>{if(typeof applyZoom==='function')applyZoom();drawManualOverlay();};}catch(e){console.error(e);alert('Render করা যায়নি: '+e.message);}finally{if(window.hideSpinner)window.hideSpinner();}}"
NEW_RENDER = "async function renderManual(){const list=items().filter(it=>it.translation&&it.translation.trim());if(!list.length){alert('কমপক্ষে একটি বাবলের বাংলা অনুবাদ লিখুন।');return;}try{if(window.showSpinner)window.showSpinner('Avro/Unicode → Bijoy conversion চলছে...');const cr=await fetch('/api/convert-bijoy',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({texts:list.map(it=>it.translation)})});if(!cr.ok)throw new Error(await cr.text());const cd=await cr.json();(cd.bijoy||[]).forEach((v,i)=>{list[i].bijoy=v;});renderManualSidebar();if(window.showSpinner)window.showSpinner('Bijoy text দিয়ে image render হচ্ছে...');const file=await currentImageFile();if(!file)throw new Error('Image unavailable');const fd=new FormData();fd.append('file',file);fd.append('items_json',JSON.stringify(list.map(it=>({...it,translation:'',bijoy:it.bijoy}))));const res=await fetch('/api/render',{method:'POST',body:fd});if(!res.ok)throw new Error(await res.text());const blob=await res.blob(),url=URL.createObjectURL(blob);try{if(typeof imageList!=='undefined'&&typeof currentIndex!=='undefined'&&imageList[currentIndex])imageList[currentIndex].renderedUrl=url;}catch(e){}const img=document.getElementById('mainImage');if(typeof activeView!=='undefined')activeView='rendered';document.getElementById('btnOriginal')?.classList.remove('active');document.getElementById('btnRendered')?.classList.add('active');img.src=url;img.onload=()=>{if(typeof applyZoom==='function')applyZoom();drawManualOverlay();};}catch(e){console.error(e);alert('Render করা যায়নি: '+e.message);}finally{if(window.hideSpinner)window.hideSpinner();}}"

RENDER_INJECT = '''\nfrom bijoy_converter import unicode_to_bijoy\n\ndef find_bijoy_font():\n    candidates=[os.environ.get('BIJOY_FONT_PATH',''),os.path.join(os.path.dirname(__file__),'fonts','SutonnyMJ.ttf'),os.path.join(os.path.dirname(__file__),'fonts','SutonnyMJ.TTF'),os.path.join(os.path.dirname(__file__),'SutonnyMJ.ttf'),'/tmp/SutonnyMJ.ttf','C:/Windows/Fonts/SutonnyMJ.ttf','C:/Windows/Fonts/SutonnyMJ.TTF','/usr/share/fonts/truetype/bijoy/SutonnyMJ.ttf']\n    for p in candidates:\n        if p and os.path.exists(p): return p\n    return None\n\nBIJOY_FONT_PATH=find_bijoy_font()\n\ndef fit_bijoy_text(draw,text,poly,bbox):\n    x0,y0,x1,y1=bbox\n    if not BIJOY_FONT_PATH: raise RuntimeError('Bijoy font not found. Add fonts/SutonnyMJ.ttf or set BIJOY_FONT_PATH.')\n    inner=[p for p in poly if len(p)>=2]\n    if len(inner)<3: inner=[[x0,y0],[x1,y0],[x1,y1],[x0,y1]]\n    miny=max(y0,min(p[1] for p in inner));maxy=min(y1,max(p[1] for p in inner));max_size=max(8,int(min(x1-x0,maxy-miny)*0.18))\n    for size in range(max_size,7,-1):\n        f=ImageFont.truetype(BIJOY_FONT_PATH,size);spacing=max(2,size//5);words=text.split();lines=[];cur=''\n        for word in words:\n            test=word if not cur else cur+' '+word;allowed=polygon_width_at(inner,miny+size,x0,x1)-16\n            if allowed<20: allowed=x1-x0-20\n            if draw.textbbox((0,0),test,font=f)[2]<=allowed: cur=test\n            else:\n                if cur: lines.append(cur)\n                cur=word\n        if cur: lines.append(cur)\n        if not lines: continue\n        total=0;heights=[]\n        for line in lines:\n            bb=draw.textbbox((0,0),line,font=f);h=bb[3]-bb[1];heights.append(h);total+=h\n        total+=spacing*(len(lines)-1)\n        if total>(maxy-miny-12): continue\n        yy=(miny+maxy-total)/2;ok=True\n        for line,h in zip(lines,heights):\n            cy=yy+h/2;allowed=polygon_width_at(inner,cy,x0,x1)-16\n            if draw.textbbox((0,0),line,font=f)[2]>max(20,allowed): ok=False;break\n            yy+=h+spacing\n        if ok:return f,lines,spacing\n    return ImageFont.truetype(BIJOY_FONT_PATH,8),[text],2\n\n@app.post('/api/convert-bijoy')\nasync def convert_bijoy(req:AutoTranslateRequest):\n    return {'bijoy':[unicode_to_bijoy(t or '') for t in req.texts]}\n\n'''

OLD_RENDER_MARKER = "@app.post('/api/render')"
OLD_RENDER_TEXT = "bbox=item.get('bbox') or [];text=(item.get('translation') or '').strip()"
NEW_RENDER_TEXT = "bbox=item.get('bbox') or [];text=(item.get('bijoy') or '').strip()"
OLD_FIT_CALL = 'font,lines,spacing=fit_polygon_text(draw,text,poly,[x0,y0,x1,y1])'
NEW_FIT_CALL = 'font,lines,spacing=fit_bijoy_text(draw,text,poly,[x0,y0,x1,y1])'

class MainLoader(importlib.machinery.SourceFileLoader):
    def get_data(self, path):
        data=super().get_data(path)
        try:
            src=data.decode('utf-8')
            src=src.replace(OLD_FIT,NEW_FIT).replace(OLD_CALL,NEW_CALL).replace(OLD_CANDIDATE,NEW_CANDIDATE).replace(OLD_UNPACK,NEW_UNPACK).replace(OLD_ROI,NEW_ROI).replace(OLD_FOCUS,NEW_FOCUS).replace(OLD_TEXTAREA_BIND,NEW_TEXTAREA_BIND).replace(OLD_SIDEBAR,NEW_SIDEBAR).replace(OLD_RENDER,NEW_RENDER).replace(OLD_RENDER_TEXT,NEW_RENDER_TEXT).replace(OLD_FIT_CALL,NEW_FIT_CALL)
            src=src.replace(OLD_RENDER_MARKER,RENDER_INJECT+OLD_RENDER_MARKER)
            data=src.encode('utf-8')
        except Exception as e:
            print('toon runtime patch skipped:',repr(e))
        return data

class MainFinder(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname!=_TARGET:return None
        spec=importlib.machinery.PathFinder.find_spec(fullname,path)
        if spec and spec.origin and isinstance(spec.loader,importlib.machinery.SourceFileLoader):spec.loader=MainLoader(fullname,spec.origin)
        return spec

sys.meta_path.insert(0,MainFinder())
