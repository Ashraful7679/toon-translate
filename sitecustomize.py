import sys, importlib.abc, importlib.machinery

_TARGET = 'main'

OLD_FIT = '''def fit_font(draw,text,max_w,max_h):
    if not FONT_PATH:return ImageFont.load_default()
    for size in range(max(10,int(min(max_h,max_w)*0.10)),7,-1):
        f=ImageFont.truetype(FONT_PATH,size)
        lines=wrap_text(text,f,max_w)
        spacing=max(2,size//5)
        bbox=draw.multiline_textbbox((0,0),'\n'.join(lines),font=f,spacing=spacing,align='center')
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
        joined='\n'.join(lines)
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
OLD_ROI = "roi=gray[y0:y1,x0:x1]\n    _,th=cv2.threshold(roi,245,255,cv2.THRESH_BINARY)\n    contours,_=cv2.findContours(th,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)"
NEW_ROI = "component=(labels[y0:y1,x0:x1]==label_idx).astype(np.uint8)*255\n    contours,_=cv2.findContours(component,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)"

JS_FOCUS_OLD = "function focusCard(i){const el=document.getElementById('bubble-card-'+i);if(el){el.scrollIntoView({behavior:'smooth',block:'center'});const inp=el.querySelector('textarea');if(inp)inp.focus();}}"
JS_FOCUS_NEW = "function scrollToBubbleBBox(b){const stage=document.getElementById('stageView'),img=document.getElementById('mainImage');if(!stage||!img||!img.naturalWidth||!b||b.length<4)return;const r=img.getBoundingClientRect(),sr=stage.getBoundingClientRect(),cx=r.left+(b[0]+b[2])/2*(r.width/img.naturalWidth),cy=r.top+(b[1]+b[3])/2*(r.height/img.naturalHeight),left=stage.scrollLeft+cx-sr.left-stage.clientWidth/2,top=stage.scrollTop+cy-sr.top-stage.clientHeight/2;stage.scrollTo({left:Math.max(0,Math.min(stage.scrollWidth-stage.clientWidth,left)),top:Math.max(0,Math.min(stage.scrollHeight-stage.clientHeight,top)),behavior:'smooth'});} function focusCard(i){const el=document.getElementById('bubble-card-'+i);if(el){el.scrollIntoView({behavior:'smooth',block:'center'});const inp=el.querySelector('textarea');if(inp){inp.focus();setTimeout(()=>scrollToBubbleBBox(items()[i]?.bbox),100);}}}"
JS_EVENTS_OLD = "ta.addEventListener('input',()=>{it.translation=ta.value;});ta.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();const n=wrap.querySelectorAll('textarea')[i+1];if(n)n.focus();}});"
JS_EVENTS_NEW = "ta.addEventListener('compositionstart',()=>ta.dataset.composing='1');ta.addEventListener('compositionend',()=>{ta.dataset.composing='0';it.translation=ta.value.normalize('NFC');});ta.addEventListener('input',()=>{it.translation=ta.value.normalize('NFC');});ta.addEventListener('focus',()=>setTimeout(()=>scrollToBubbleBBox(it.bbox),100));ta.addEventListener('click',()=>setTimeout(()=>scrollToBubbleBBox(it.bbox),100));ta.addEventListener('keydown',e=>{if(e.isComposing||ta.dataset.composing==='1')return;if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();const n=wrap.querySelectorAll('textarea')[i+1];if(n){n.focus();setTimeout(()=>scrollToBubbleBBox(list[i+1]?.bbox),100);}}});"

# Bengali render isolation: keep the existing render pipeline, but replace only
# the measurement/draw calls used for translated text with HarfBuzz shaping.
OLD_BN_WIDTH = 'test_w=draw.textbbox((0,0),test,font=f)[2]'
NEW_BN_WIDTH = 'test_w=bengali_text_width(test,f)'
OLD_BN_CHECK = 'if draw.textbbox((0,0),line,font=f)[2]>max(20,allowed):ok=False;break'
NEW_BN_CHECK = 'if bengali_text_width(line,f)>max(20,allowed):ok=False;break'
OLD_BN_DRAW = """            block='\n'.join(lines)
            bb=draw.multiline_textbbox((0,0),block,font=font,spacing=spacing,align='center')
            tw,th=bb[2]-bb[0],bb[3]-bb[1]
            tx=x0+(x1-x0-tw)/2;ty=y0+(y1-y0-th)/2
            draw.multiline_text((tx,ty),block,font=font,fill='black',spacing=spacing,align='center')"""
NEW_BN_DRAW = """            if hasattr(font, 'path'):
                draw_bengali_block(draw,(x0,y0,x1,y1),lines,font,spacing=spacing,fill='black',align='center')
            else:
                block='\n'.join(lines)
                draw.multiline_text((x0,y0),block,font=font,fill='black',spacing=spacing,align='center')"""

class MainLoader(importlib.machinery.SourceFileLoader):
    def get_data(self, path):
        data = super().get_data(path)
        try:
            src = data.decode('utf-8')
            if OLD_FIT in src:
                src = src.replace(OLD_FIT, NEW_FIT)
            src = src.replace(OLD_CALL, NEW_CALL)
            src = src.replace(OLD_CANDIDATE, NEW_CANDIDATE)
            src = src.replace(OLD_UNPACK, NEW_UNPACK)
            src = src.replace(OLD_ROI, NEW_ROI)
            src = src.replace(JS_FOCUS_OLD, JS_FOCUS_NEW)
            src = src.replace(JS_EVENTS_OLD, JS_EVENTS_NEW)
            src = src.replace(OLD_BN_WIDTH, NEW_BN_WIDTH)
            src = src.replace(OLD_BN_CHECK, NEW_BN_CHECK)
            src = src.replace(OLD_BN_DRAW, NEW_BN_DRAW)
            src = "from bengali_renderer import text_width as bengali_text_width, draw_bengali_block\n" + src
            data = src.encode('utf-8')
        except Exception as e:
            print('toon runtime patch skipped:', e)
        return data

class MainFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != _TARGET:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec and spec.origin and isinstance(spec.loader, importlib.machinery.SourceFileLoader):
            spec.loader = MainLoader(fullname, spec.origin)
        return spec

sys.meta_path.insert(0, MainFinder())
