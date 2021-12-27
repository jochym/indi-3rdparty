from vpython import *

Az = 0
Alt = 0
r = 9.0
dr = 1
faw = 6
fah = 20
fal = 3
fi = 6
l = 24
s = 5
pnts = 30

base = cylinder(radius=r+1, length=2, 
            pos=vector(0,0,0), axis=vector(0,1,0) )

hbase = cylinder(radius=r, length=2, 
            pos=vector(0,2,0), axis=vector(0,1,0), color=color.green)

forkarm = box(length=fal, width=faw, height=fah, 
                up=vector(0,1,0), color=color.orange)

altax = cylinder(radius = faw/2, length=fal, color=color.red)

tube = cylinder(radius = r-fal)


Nvec = vector(0,0,pnts)
# arrow(axis=Nvec, shaftwidth=dr, headwidth=2*dr, round=True)
# arrow(axis=N.axis.rotate(pi/2, vector(0,1,0)), shaftwidth=dr, headwidth=2*dr, round=True)
# arrow(axis=N.axis.rotate(pi, vector(0,1,0)), shaftwidth=dr, headwidth=2*dr, round=True)
# arrow(axis=N.axis.rotate(3*pi/2, vector(0,1,0)), shaftwidth=dr, headwidth=2*dr, round=True)
label(pos=1.2*Nvec, text='N')
label(pos=1.2*Nvec.rotate(pi/2, vector(0,1,0)), text='W')
label(pos=1.2*Nvec.rotate(pi, vector(0,1,0)), text='S')
label(pos=1.2*Nvec.rotate(3*pi/2, vector(0,1,0)), text='E')

crot = vector(0, 2+fah, 0)

azpnt = arrow(pos = crot, axis=Nvec, shaftwidth=dr, headwidth=2*dr, round=True)
altpnt = arrow(pos = crot, axis=Nvec, shaftwidth=dr, headwidth=2*dr, round=True)

for az in range(0,360,15):
    v = vector(sin(pi*az/180), 0, cos(pi*az/180))
    cylinder(pos=v*pnts + crot, axis=v*(dr*2), length=2*dr, radius=dr/5, color=color.yellow)

alt_scale = []
for al in range(-90, 91, 10):
    v = vector(sin(pi*al/180), cos(pi*al/180), 0)
    alt_scale.append(cylinder(pos=v*pnts + crot, axis=v*(dr*2), length=2*dr, radius=dr/5, color=color.yellow))

dalt = 0.1
daz = 0.1
maxalt = pi/2
minalt = -pi/10

pos = label(xoffset=6*fah, yoffset=6*fah, line=False, align='left', font='monospace')

sphere(pos=crot, radius=pnts, color=color.blue, opacity=0.3)

def getHMS(ang):
    a = 180*ang/pi
    a /=15
    a = int(a*36000)
    S = a % 600
    M = (a // 600) % 60
    H = (a // 600) // 60
    assert abs(180*ang/pi - 15*(((S/600 + M)/60) + H)) < 0.2*15/60/60
    return f'{H:02d}<sup>h</sup>{M:02d}<sup>m</sup>{S//10:02d}<sup>s</sup>{S%10:1d}'
    return f'{H:02d}<sup>h</sup>{M:02d}<sup>m</sup>{S/10:04.1f}<sup>s</sup>'

def getDMS(ang):
    a = 180*ang/pi
    s = 1 if a>=0 else -1
    a = abs(a)
    a = int(a*36000)
    S = a % 600
    M = a // 600 % 60
    D = a // 600 // 60
    assert abs(180*ang/pi - s*(((S/600 + M)/60) + D)) < 0.2/60/60
    return f'{s*D:+04d}<sup>°</sup>{M:02d}<sup>\'</sup>{S//10:02d}<sup>"</sup>{S%10:1d}'
    return f'{s*D:+03d}°{M:02d}\'{S/10:04.1f}"'



while True:
    rate(30)
    azvec = vector(0, 0, 1).rotate(Az + pi/2, axis=vector(0,1,0))
    pntvec = vector(0, 0, 1).rotate(Alt, axis=vector(-1,0,0)).rotate(Az, axis=vector(0,1,0))

    azpnt.axis = vector(0, 0, 1).rotate(Az, axis=vector(0,1,0)) * azpnt.length
    altpnt.axis = pntvec * altpnt.length
    azdir = vector(0, 0, 1).rotate(Az, axis=vector(0,1,0))

    for alv, a in zip(alt_scale, range(-90, 91, 10)):
        v = vector(0, sin(pi*a/180), cos(pi*a/180))
        v.rotate_in_place(Az, axis=vector(0,1,0))
        alv.pos = v*pnts + crot
        alv.axis = axis=v*(dr*2)

    forkarm.pos = azvec*(r-fal/2) + vector(0, 2+fah/2, 0)
    forkarm.axis = azvec*fal

    altax.pos = azvec*(r-fal-dr) + vector(0, 2+fah, 0)
    altax.axis = azvec*(fal-dr)

    tube.pos = vector(0, 2+fah, 0) - pntvec*(s)
    tube.axis = pntvec*(l)

    pos.text = f'<b>Position</b>\n<b> Az:</b>{getDMS(Az)}\n<b>Alt:</b>{getDMS(Alt)}'

    Az += daz*pi/180
    Az %= 2*pi

    Alt += dalt*pi/180
    if Alt > maxalt or Alt < minalt:
        dalt=-dalt
    
    
