"""Plain engineering schematics, with no visible headers or footer captions."""

from __future__ import annotations
import json
import math
from pathlib import Path
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile
from PIL import Image, ImageChops, ImageDraw, ImageFont

HERE=Path(__file__).resolve().parent
S=2
INK='#222222'
BLUE='#E4EDFA'
GREEN='#E4EEDD'
YELLOW='#FFF2D6'
LILAC='#E9E1EF'
GRAY='#F5F5F3'
RED='#F6E3E0'

class Figure:
    def __init__(self,title,height=1250):
        self.width,self.height=1500,height
        self.title=title
        self.image=Image.new('RGB',(1500*S,height*S),'white')
        self.draw=ImageDraw.Draw(self.image)
        self.svg=[]
        self.nodes=[]
        self.labels=[]
    def font(self,size=22,bold=False):
        return ImageFont.truetype(str(Path('C:/Windows/Fonts')/('arialbd.ttf' if bold else 'arial.ttf')),size*S)
    def measure(self,text,size=22,bold=False):
        return self.draw.textlength(text,font=self.font(size,bold))/S
    def text(self,x,y,text,size=22,bold=False,align='left'):
        w=self.measure(text,size,bold)
        left=x-w/2 if align=='center' else x
        if left<0 or left+w>self.width or y<0 or y+size>self.height:
            raise ValueError(f'Label outside canvas: {text}')
        self.draw.text((left*S,y*S),text,fill=INK,font=self.font(size,bold),anchor='lt')
        self.svg.append(f'<text x="{left:.2f}" y="{y:.2f}" font-family="Arial, sans-serif" font-size="{size}" font-weight="{700 if bold else 400}" fill="{INK}" dominant-baseline="text-before-edge">{escape(text)}</text>')
        self.labels.append(text)
    def wrap(self,text,width,size,bold=False):
        lines=[]
        for line in text.split('\n'):
            current=''
            for word in line.split():
                candidate=f'{current} {word}'.strip()
                if self.measure(candidate,size,bold)<=width:
                    current=candidate
                else:
                    if not current: raise ValueError(f'Word too wide: {word}')
                    lines.append(current)
                    current=word
            lines.append(current)
        return lines
    def content(self,x,y,w,h,title,body='',size=22):
        titles=self.wrap(title,w-30,size+2,True)
        bodies=self.wrap(body,w-30,size) if body else []
        a,b=(size+2)*1.23,size*1.26
        used=len(titles)*a+(10 if bodies else 0)+len(bodies)*b
        if used>h-12: raise ValueError(f'Node too small: {title!r}, {used:.1f} > {h-12:.1f}')
        cursor=y+(h-used)/2
        for line in titles:
            self.text(x+w/2,cursor,line,size+2,True,'center')
            cursor+=a
        if bodies: cursor+=10
        for line in bodies:
            self.text(x+w/2,cursor,line,size,False,'center')
            cursor+=b
    def rect(self,x,y,w,h,fill='white',stroke=INK,line_width=1.5):
        self.draw.rectangle(tuple(round(v*S) for v in (x,y,x+w,y+h)),fill=fill,outline=stroke,width=max(1,round(line_width*S)))
        self.svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="{stroke}" stroke-width="{line_width}"/>')
    def polygon(self,points,fill='white',stroke=INK):
        coords=[(round(x*S),round(y*S)) for x,y in points]
        self.draw.polygon(coords,fill=fill)
        self.draw.line(coords+[coords[0]],fill=stroke,width=3,joint='curve')
        value=' '.join(f'{x},{y}' for x,y in points)
        self.svg.append(f'<polygon points="{value}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
    def ellipse(self,x,y,w,h,fill='white',stroke=INK):
        self.draw.ellipse(tuple(round(v*S) for v in (x,y,x+w,y+h)),fill=fill,outline=stroke,width=3)
        self.svg.append(f'<ellipse cx="{x+w/2}" cy="{y+h/2}" rx="{w/2}" ry="{h/2}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
    def segment(self,points,dash=False,width=1.5):
        if not dash:
            self.draw.line([(round(x*S),round(y*S)) for x,y in points],fill=INK,width=max(1,round(width*S)),joint='curve')
        else:
            for (x0,y0),(x1,y1) in zip(points,points[1:]):
                length=math.hypot(x1-x0,y1-y0)
                for start in range(0,math.ceil(length),12):
                    end=min(start+7,length)
                    a=(x0+(x1-x0)*start/length,y0+(y1-y0)*start/length)
                    b=(x0+(x1-x0)*end/length,y0+(y1-y0)*end/length)
                    self.draw.line([(round(x*S),round(y*S)) for x,y in (a,b)],fill=INK,width=2)
        value=' '.join(f'{x},{y}' for x,y in points)
        dash_attr=' stroke-dasharray="7 5"' if dash else ''
        self.svg.append(f'<polyline points="{value}" fill="none" stroke="{INK}" stroke-width="{width}"{dash_attr}/>')
    def head(self,previous,end):
        angle=math.atan2(end[1]-previous[1],end[0]-previous[0])
        bx,by=end[0]-11*math.cos(angle),end[1]-11*math.sin(angle)
        points=[end,(bx+4.5*math.sin(angle),by-4.5*math.cos(angle)),(bx-4.5*math.sin(angle),by+4.5*math.cos(angle))]
        self.draw.polygon([(round(x*S),round(y*S)) for x,y in points],fill=INK)
        value=' '.join(f'{x:.2f},{y:.2f}' for x,y in points)
        self.svg.append(f'<polygon points="{value}" fill="{INK}"/>')
    def arrow(self,points,both=False):
        self.segment(points)
        self.head(points[-2],points[-1])
        if both: self.head(points[1],points[0])
    def frame(self,x,y,w,h,label):
        self.segment([(x,y),(x+w,y),(x+w,y+h),(x,y+h),(x,y)],dash=True,width=1)
        if label: self.text(x+16,y+14,label,size=21)
    def badge(self,x,y,number):
        self.ellipse(x-14,y-14,28,28,LILAC,'#896A99')
        self.text(x,y-10,str(number),size=18,align='center')
    def node(self,x,y,w,h,title,body='',fill='white',shape='box',number=None,size=22):
        tx,ty,tw,th=x,y,w,h
        if shape=='box': self.rect(x,y,w,h,fill)
        elif shape=='stack':
            self.rect(x+24,y-20,w,h,fill,stroke='#75905F')
            self.rect(x+12,y-10,w,h,fill,stroke='#75905F')
            self.rect(x,y,w,h,fill)
        elif shape=='input':
            self.polygon([(x+22,y),(x+w,y),(x+w-22,y+h),(x,y+h)],fill)
            tx,tw=x+20,w-40
        elif shape=='diamond':
            self.polygon([(x+w/2,y),(x+w,y+h/2),(x+w/2,y+h),(x,y+h/2)],fill)
            tx,tw=x+w*.15,w*.7
            ty,th=y+h*.2,h*.6
        elif shape=='cylinder':
            ry=18
            self.ellipse(x,y+h-2*ry,w,2*ry,fill)
            self.draw.rectangle(tuple(round(v*S) for v in (x,y+ry,x+w,y+h-ry)),fill=fill)
            self.svg.append(f'<rect x="{x}" y="{y+ry}" width="{w}" height="{h-2*ry}" fill="{fill}"/>')
            self.segment([(x,y+ry),(x,y+h-ry)])
            self.segment([(x+w,y+ry),(x+w,y+h-ry)])
            self.ellipse(x,y,w,2*ry,fill)
            ty,th=y+2*ry+3,h-2*ry-6
        elif shape=='cloud':
            base=[(0,.53),(.04,.33),(.18,.28),(.19,.13),(.34,.10),(.47,.03),(.60,.12),(.76,.11),(.87,.28),(.96,.32),(.94,.46),(1,.58),(.94,.74),(.76,.80),(.59,.84),(.45,.94),(.28,.88),(.14,.79),(.04,.72)]
            anchors=[(x+a*w,y+b*h) for a,b in base]
            points=[]
            paths=[f'M {anchors[0][0]:.2f} {anchors[0][1]:.2f}']
            for i in range(len(anchors)):
                p0,p1,p2,p3=[anchors[j%len(anchors)] for j in (i-1,i,i+1,i+2)]
                c1=(p1[0]+(p2[0]-p0[0])/6,p1[1]+(p2[1]-p0[1])/6)
                c2=(p2[0]-(p3[0]-p1[0])/6,p2[1]-(p3[1]-p1[1])/6)
                paths.append(f'C {c1[0]:.2f} {c1[1]:.2f} {c2[0]:.2f} {c2[1]:.2f} {p2[0]:.2f} {p2[1]:.2f}')
                for step in range(20):
                    t=step/20
                    points.append(tuple((1-t)**3*p1[k]+3*(1-t)**2*t*c1[k]+3*(1-t)*t*t*c2[k]+t**3*p2[k] for k in (0,1)))
            coords=[(round(a*S),round(b*S)) for a,b in points]
            self.draw.polygon(coords,fill=fill)
            self.draw.line(coords+[coords[0]],fill=INK,width=3,joint='curve')
            self.svg.append(f'<path d="{" ".join(paths)} Z" fill="{fill}" stroke="{INK}" stroke-width="1.5"/>')
            tx,tw=x+32,w-64
            ty,th=y+h*.22,h*.57
        else: raise ValueError(shape)
        self.content(tx,ty,tw,th,title,body,size)
        if number is not None: self.badge(x+3,y+14,number)
        self.nodes.append({'title':title,'body':body,'shape':shape,'bounds':[x,y,x+w,y+h]})
    def save(self,filename):
        bbox=ImageChops.difference(self.image,Image.new('RGB',self.image.size,'white')).getbbox()
        assert bbox is not None
        margin=35*S
        x0=max(0,bbox[0]-margin)//S*S
        y0=max(0,bbox[1]-margin)//S*S
        x1=min(self.image.width,bbox[2]+margin)
        y1=min(self.image.height,bbox[3]+margin)
        self.image=self.image.crop((x0,y0,x1,y1))
        png,svg=HERE/f'{filename}.png',HERE/f'{filename}.svg'
        self.image.save(png,optimize=True)
        doc=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.image.width/S:g}" height="{self.image.height/S:g}" viewBox="{x0/S:g} {y0/S:g} {self.image.width/S:g} {self.image.height/S:g}" role="img" aria-labelledby="title">',f'<title id="title">{escape(self.title)}</title>',f'<rect x="{x0/S}" y="{y0/S}" width="{self.image.width/S}" height="{self.image.height/S}" fill="white"/>',*self.svg,'</svg>']
        svg.write_text('\n'.join(doc),encoding='utf-8')
        return {'file':png.name,'svg':svg.name,'title':self.title,'size':list(self.image.size),'bytes':png.stat().st_size,'style':'classic_engineering','visible_header':False,'visible_footer':False,'nodes':self.nodes,'labels':self.labels}

def pipeline():
    f=Figure('Citizen observation workflow',height=1240)
    f.frame(80,270,650,310,'Container photo')
    for points in [[(404,125),(535,125)],[(835,125),(970,125)],[(1100,210),(1100,240),(55,240),(55,410),(120,410)],[(1100,210),(1100,300)],[(350,410),(435,410)],[(685,410),(860,410),(860,575),(980,575)],[(1120,400),(1120,497)],[(560,475),(560,700)],[(1120,646),(1120,755),(970,755)],[(85,130),(35,130),(35,755),(450,755)],[(710,810),(710,945),(1030,945)],[(1195,1015),(1195,1055),(255,1055),(255,1100)],[(1195,1015),(1195,1055),(705,1055),(705,1100)],[(1195,1015),(1195,1100)]]: f.arrow(points)
    f.text(70,724,'Field answers',size=21)
    f.node(75,70,340,110,'Citizen report','Photo, answers, place and time',BLUE,shape='input',number=1)
    f.node(535,70,300,110,'Image check','Size, blur and brightness',number=2)
    f.node(970,50,260,160,'Analysis\nmode',fill=GRAY,shape='diamond',size=21)
    f.node(120,355,230,120,'YOLO11n','Container boxes',GREEN,shape='stack',number=3,size=21)
    f.node(435,355,250,120,'YOLO11s-seg','Water inside containers',GREEN,shape='stack',size=21)
    f.node(980,300,280,100,'River photo','Skip container models',GRAY)
    f.node(980,490,280,170,'Kimi API','Scene description',GRAY,shape='cloud',number=4,size=21)
    f.node(450,700,520,110,'Combine evidence','Risk and confidence kept separate',LILAC,number=5)
    f.node(1030,875,330,140,'Save observation','Photo, location and result',YELLOW,shape='cylinder',number=6,size=21)
    f.node(80,1100,350,95,'Map + canal passport','History, signs and alerts',BLUE,size=21)
    f.node(530,1100,350,95,'Verification','Volunteer / expert findings',YELLOW,size=21)
    f.node(1020,1100,350,95,'Missions + dashboard','Activities and progress',GREEN,size=21)
    return f.save('01-observation-pipeline')

def training():
    f=Figure('Training and evaluation',height=1220)
    for points in [[(370,130),(455,130)],[(645,210),(645,270),(350,270),(350,330)],[(645,210),(645,270),(1150,270),(1150,330)],[(350,490),(350,590)],[(1150,490),(1150,590)],[(350,775),(350,860)],[(1150,775),(1150,860)],[(600,955),(650,955)],[(960,955),(890,955)],[(770,1005),(770,1070)]]: f.arrow(points)
    f.node(60,60,310,150,'VisText-Mosquito v2','Mendeley Data\nCC BY 4.0',YELLOW,shape='cylinder',number=1,size=21)
    f.node(455,60,380,150,'Clean + group scenes','Deduplicate and remap labels\nGroup similar photos\nSplit seed: 42',number=2,size=21)
    f.node(145,330,410,160,'Container detection','1,640 images\nTrain / val / test: 1,132 / 341 / 167',BLUE,shape='cylinder',size=21)
    f.node(960,330,380,160,'Water masks','141 images\nTrain / val / test: 89 / 33 / 19',BLUE,shape='cylinder',size=21)
    f.node(140,590,420,185,'YOLO11n / YOLO11s','n: 45 epochs / s: 50 epochs\n640 px, PyTorch + CUDA\nTraining seed: 0',GREEN,shape='stack',number=3,size=21)
    f.node(960,590,400,185,'YOLO11n-seg / YOLO11s-seg','n-seg: 62 / s-seg: 200 epochs\n640 px, PyTorch + CUDA\nTraining seed: 0',GREEN,shape='stack',size=21)
    f.node(60,860,540,170,'Detector test: 167 images','YOLO11n: P 75.43% / R 82.59%\nmAP50 0.7834 / mAP50–95 0.5057\nYOLO11s: P 76.33% / R 81.65%\nmAP50 0.7550 / mAP50–95 0.5325',LILAC,number=4,size=21)
    f.node(960,860,400,170,'Container-water masks','19 test images\nSupporting evidence\nUsed only in container mode',LILAC,size=21)
    f.node(650,900,240,105,'Export ONNX','Detector + water model',GRAY,size=20)
    f.node(650,1070,240,95,'CPU inference','ONNX Runtime',BLUE,number=5,size=21)
    return f.save('02-training-and-evaluation')

def architecture():
    f=Figure('Application and deployment architecture',height=1100)
    f.frame(30,200,1010,835,'Amazon Linux / EC2 / Docker Compose')
    f.frame(445,365,515,465,'Web container')
    for points in [[(335,100),(535,100)],[(695,145),(695,245)],[(695,330),(695,425)],[(500,465),(340,465)],[(695,555),(695,655)],[(500,520),(400,520),(400,875),(360,875)],[(880,470),(1010,470),(1010,150),(1110,150)],[(880,520),(1065,520),(1065,737),(1110,737)]]: f.arrow(points,both=True)
    f.node(55,60,280,80,'DNS / sslip.io',fill=GRAY,number=1,size=21)
    f.node(535,60,320,85,'User browser','HTML, JS, Leaflet • VI / EN',BLUE,number=2,size=21)
    f.node(535,245,320,85,'Caddy','HTTPS • ports 80 / 443',BLUE,number=3,size=21)
    f.node(500,425,380,130,'FastAPI application','Routes, scoring and verification\nHTTPX API adapters',GREEN,number=4,size=21)
    f.node(530,655,340,130,'ONNX Runtime / CPU','YOLO11n + YOLO11s-seg\nOpenCV + NumPy',GREEN,shape='stack',number=5,size=21)
    f.node(70,380,270,170,'PostgreSQL + PostGIS','Reports and spatial queries\nPersistent DB volume',YELLOW,shape='cylinder',number=6,size=20)
    f.node(70,805,290,140,'Photo volume','Processed report images',YELLOW,shape='cylinder',number=7,size=21)
    f.node(1110,55,330,180,'Kimi API','Model Studio / kimi-k3\nImage + prompt → JSON',GRAY,shape='cloud',number=8,size=20)
    f.node(1110,610,330,240,'Reference services','OneAquaHealth\nOpen-Meteo / news RSS\nOSM geometry',GRAY,shape='cloud',number=9,size=20)
    return f.save('03-system-architecture')

def evidence():
    f=Figure('Evidence and review routing',height=1390)
    for points in [[(215,205),(215,265),(620,265),(620,320)],[(750,195),(750,320)],[(1260,205),(1260,265),(880,265),(880,320)],[(660,440),(660,490),(325,490),(325,545)],[(860,440),(860,490),(1095,490),(1095,525)],[(325,650),(325,710),(750,710),(750,755)],[(1095,680),(1095,710),(750,710),(750,755)],[(595,827),(230,827),(230,980)],[(750,900),(750,980)],[(905,827),(1240,827),(1240,980)],[(1240,1090),(1240,1180)],[(1060,1250),(850,1250)]]: f.arrow(points)
    f.text(250,858,'No mandatory review',size=21)
    f.text(775,925,'Confirm / missing data',size=19)
    f.text(1015,858,'Serious signs / low C',size=21)
    f.node(50,65,330,140,'Local model evidence','Container / water findings\nBase weight: 0.5',GREEN,shape='stack',number=1,size=21)
    f.node(580,35,340,175,'Kimi suggestions','Visible signs\nBase weight: 0.3',GRAY,shape='cloud',number=2,size=20)
    f.node(1090,65,340,140,'Field answers','Base weight: 0.2\nAdjusted by reliability',BLUE,shape='input',number=3,size=21)
    f.node(500,320,500,120,'Fuse available sources','Renormalize weights\nRecord conflicts and unknowns',LILAC,number=4,size=21)
    f.node(110,545,430,105,'Risk / ecology / impact','Rule-based indicators',YELLOW,size=22)
    f.node(820,525,550,155,'Confidence','0.5 × agreement + 0.3 × coverage\n+ 0.2 × image quality',BLUE,size=22)
    f.node(595,755,310,145,'Review route',fill=GRAY,shape='diamond',size=21)
    f.node(60,980,340,110,'Preliminary result','Unverified river: at most yellow',GREEN,size=21)
    f.node(525,980,360,110,'Ask reporter','Confirm or correct answers',YELLOW,size=21)
    f.node(1060,980,360,110,'Verification queue','Human review required',RED,number=5,size=21)
    f.node(1060,1180,360,155,'Volunteer / expert','Orange: on-site confirmation\nRed: expert confirmation',GREEN,size=21)
    f.node(490,1180,360,150,'Decision history','Update reports and alerts',YELLOW,shape='cylinder',number=6,size=21)
    return f.save('04-evidence-and-verification')

def main():
    results=[pipeline(),training(),architecture(),evidence()]
    (HERE/'manifest.json').write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding='utf-8')
    (HERE/'preview.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AquaPulse figures</title><style>body{font:14px Arial;margin:24px;background:white;color:#222}main{max-width:1120px;margin:auto}article{margin:32px 0 60px}img{display:block;width:100%;height:auto}nav{margin-bottom:14px}a{color:#355477}</style><main>'+''.join(f'<article><nav>{i+1}. <a href="{r["file"]}">PNG</a> / <a href="{r["svg"]}">SVG</a></nav><img src="{r["file"]}" alt="{escape(r["title"])}"></article>' for i,r in enumerate(results))+'</main></html>',encoding='utf-8')
    (HERE/'README.md').write_text('# AquaPulse project diagrams\n\nFour classic engineering diagrams with thin black connectors, pastel nodes, database cylinders and cloud shapes. Visible title banners and external captions have been removed.\n\n| Image | Story location |\n| --- | --- |\n| 01-observation-pipeline.png | What it does |\n| 02-training-and-evaluation.png | Detector evaluation |\n| 03-system-architecture.png | Deployment |\n| 04-evidence-and-verification.png | Evidence combination |\n\nPNGs are ready to upload. SVGs are editable. Open preview.html to view all four. The online submission needs uploaded image URLs instead of the local paths in ../project-story.en.md.\n\nRegenerate: backend/.venv/Scripts/python.exe docs/project-story-figures/render_figures.py\n',encoding='utf-8')
    archive=HERE/'AquaPulse-Project-Story-Figures.zip'
    with ZipFile(archive,'w',ZIP_DEFLATED) as bundle:
        for item in results:
            for key in ('file','svg'): bundle.write(HERE/item[key],item[key])
        for name in ('preview.html','manifest.json','README.md'): bundle.write(HERE/name,name)
    print(json.dumps({'figures':[{k:r[k] for k in ('file','size','bytes','visible_header','visible_footer')} for r in results],'zip':archive.name},indent=2))

if __name__=='__main__': main()
