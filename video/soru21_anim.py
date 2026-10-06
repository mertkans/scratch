import math, sys, subprocess
from multiprocessing import Pool
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
SS = 2
FPS = 30
DUR = 66.0

FD = "/usr/share/fonts/truetype/dejavu/"
_fc = {}
def font(size, bold=False):
    key = (size, bold)
    if key not in _fc:
        _fc[key] = ImageFont.truetype(FD + ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"), int(size * SS))
    return _fc[key]

BG = (250, 247, 240)
INK = (34, 34, 40)
GRAY = (120, 120, 128)
BLUE = (37, 99, 235)
ORANGE = (224, 122, 31)
GREEN = (34, 150, 90)
PURPLE = (126, 58, 200)
RED = (212, 48, 58)

def rgba(c, a):
    return (c[0], c[1], c[2], int(max(0, min(1, a)) * 255))

def ease(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)

def prog(t, t0, t1):
    return ease((t - t0) / (t1 - t0))

def vis(t, t_in, t_out=None, f=0.45):
    a = prog(t, t_in, t_in + f)
    if t_out is not None:
        a *= 1 - prog(t, t_out, t_out + f)
    return a

# --- geometry -------------------------------------------------------------
SQ = 760
X0 = (W - SQ) / 2
Y0 = 560

def P(p):
    x, y = p
    return (X0 + x * SQ, Y0 + (1 - y) * SQ)

def geo(k):
    return dict(A=(0, 1), B=(1, 1), C=(1, 0), D=(0, 0), K=(k, 1),
                L=((1 + k) / 2, (1 - k) / 2), E=(0, (1 - k) / 2), F=((1 + k) / 2, 1))

def S(p):  # to supersampled pixel coords
    x, y = P(p)
    return (x * SS, y * SS)

def lerp(a, b, u):
    return (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u)

def ang(a, b):  # math angle of vector a->b in degrees (ccw, y up)
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))

# --- drawing helpers (inputs in math coords) ------------------------------
def seg(d, a, b, col, w, alpha=1, u=1):
    if alpha <= 0 or u <= 0:
        return
    b2 = lerp(a, b, u)
    d.line([S(a), S(b2)], fill=rgba(col, alpha), width=int(w * SS))
    r = w * SS / 2
    for p in (S(a), S(b2)):
        d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=rgba(col, alpha))

def dashed(d, a, b, col, w, alpha=1, u=1, dash=18, gap=12):
    if alpha <= 0 or u <= 0:
        return
    pa, pb = P(a), P(lerp(a, b, u))
    L = math.dist(pa, pb)
    if L < 1:
        return
    ux, uy = (pb[0] - pa[0]) / L, (pb[1] - pa[1]) / L
    s = 0
    while s < L:
        e = min(L, s + dash)
        d.line([((pa[0] + ux * s) * SS, (pa[1] + uy * s) * SS),
                ((pa[0] + ux * e) * SS, (pa[1] + uy * e) * SS)], fill=rgba(col, alpha), width=int(w * SS))
        s += dash + gap

def dot(d, p, col, r=8, alpha=1):
    if alpha <= 0:
        return
    x, y = S(p)
    r *= SS
    d.ellipse([x - r, y - r, x + r, y + r], fill=rgba(col, alpha))

def poly(d, pts, col, alpha):
    if alpha <= 0:
        return
    d.polygon([S(p) for p in pts], fill=rgba(col, alpha))

def sector(d, c, r, a0, a1, col, alpha):
    if alpha <= 0:
        return
    x, y = S(c)
    r *= SS
    d.pieslice([x - r, y - r, x + r, y + r], -a1, -a0, fill=rgba(col, alpha))

def arc(d, c, r, a0, a1, col, w, alpha=1):
    if alpha <= 0:
        return
    x, y = S(c)
    r *= SS
    d.arc([x - r, y - r, x + r, y + r], -a1, -a0, fill=rgba(col, alpha), width=int(w * SS))

def right_mark(d, p, q1, q2, col, size=24, w=3, alpha=1):
    if alpha <= 0:
        return
    pp, a, b = P(p), P(q1), P(q2)
    def unit(v):
        n = math.hypot(*v); return (v[0] / n, v[1] / n)
    u = unit((a[0] - pp[0], a[1] - pp[1]))
    v = unit((b[0] - pp[0], b[1] - pp[1]))
    p1 = (pp[0] + u[0] * size, pp[1] + u[1] * size)
    p2 = (pp[0] + (u[0] + v[0]) * size, pp[1] + (u[1] + v[1]) * size)
    p3 = (pp[0] + v[0] * size, pp[1] + v[1] * size)
    d.line([(p1[0] * SS, p1[1] * SS), (p2[0] * SS, p2[1] * SS), (p3[0] * SS, p3[1] * SS)],
           fill=rgba(col, alpha), width=int(w * SS), joint="curve")

def ticks(d, a, b, n, col, alpha=1, size=13, w=4, gap=9):
    if alpha <= 0:
        return
    pa, pb = P(a), P(b)
    m = ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2)
    L = math.dist(pa, pb)
    ux, uy = (pb[0] - pa[0]) / L, (pb[1] - pa[1]) / L
    nx, ny = -uy, ux
    for i in range(n):
        off = (i - (n - 1) / 2) * gap
        cx, cy = m[0] + ux * off, m[1] + uy * off
        d.line([((cx - nx * size) * SS, (cy - ny * size) * SS), ((cx + nx * size) * SS, (cy + ny * size) * SS)],
               fill=rgba(col, alpha), width=int(w * SS))

def text_at(d, xy, s, size, col, alpha=1, bold=False, anchor="mm"):
    if alpha <= 0:
        return
    d.text((xy[0] * SS, xy[1] * SS), s, font=font(size, bold), fill=rgba(col, alpha), anchor=anchor)

def label(d, p, s, off, col=INK, alpha=1, size=44):
    x, y = P(p)
    text_at(d, (x + off[0], y + off[1]), s, size, col, alpha, bold=True)

# --- rich text: ^ABC^ = angle with hat, *...* = accent colour --------------
def parse(s):
    runs, hat, acc, buf = [], False, False, ""
    for ch in s:
        if ch in "^*":
            if buf:
                runs.append((buf, hat, acc)); buf = ""
            if ch == "^": hat = not hat
            else: acc = not acc
        else:
            buf += ch
    if buf:
        runs.append((buf, hat, acc))
    # split into words, keeping styles
    words, cur = [], []
    for txt, h, a in runs:
        parts = txt.split(" ")
        for i, p in enumerate(parts):
            if i > 0:
                words.append(cur); cur = []
            if p:
                cur.append((p, h, a))
    words.append(cur)
    return [w for w in words if w]

def wlen(word, size, bold):
    f = font(size, bold)
    return sum(f.getlength(t) for t, _, _ in word) / SS

def rich_block(d, s, x, y, maxw, size, col, acc_col, alpha=1, bold=False, lh=1.5, center=False):
    if alpha <= 0:
        return y
    words = parse(s)
    sp = font(size, bold).getlength(" ") / SS
    lines, cur, cw = [], [], 0
    for wd in words:
        l = wlen(wd, size, bold)
        if cur and cw + sp + l > maxw:
            lines.append((cur, cw)); cur, cw = [], 0
        cw = cw + (sp if cur else 0) + l
        cur.append(wd)
    if cur:
        lines.append((cur, cw))
    f = font(size, bold)
    for line, lw in lines:
        cx = x + (maxw - lw) / 2 if center else x
        for wi, wd in enumerate(line):
            if wi > 0:
                cx += sp
            for t, h, a in wd:
                c = acc_col if a else col
                d.text((cx * SS, y * SS), t, font=f, fill=rgba(c, alpha), anchor="ls")
                tw = f.getlength(t) / SS
                if h:
                    top = y - size * 0.78
                    hy = top - size * 0.17
                    d.line([(cx * SS, (hy + size * 0.16) * SS), ((cx + tw / 2) * SS, (hy - size * 0.04) * SS),
                            ((cx + tw) * SS, (hy + size * 0.16) * SS)], fill=rgba(c, alpha), width=int(max(2, size / 14) * SS))
                cx += tw
        y += size * lh
    return y

def rrect(d, box, r, fill, outline=None, w=0):
    b = [v * SS for v in box]
    d.rounded_rectangle(b, radius=r * SS, fill=fill, outline=outline, width=int(w * SS))

# --- script ---------------------------------------------------------------
CAPS = [
    (2.8, 8.5, "Önce verilenler: ABCD bir kare. [DL] ile [LK] birbirine dik ve boyları eşit. Aradığımız açı *α = m(^LCB^)*."),
    (8.5, 14.0, "Bu durumda *DLK ikizkenar dik üçgen*. Asıl soru şu: L noktası karenin tam olarak neresinde?"),
    (14.0, 21.0, "L'den [AD] ve [AB] kenarlarına dikme indirelim, ayaklar E ve F olsun. AELF bir dikdörtgen, yani *m(^ELF^) = 90°*."),
    (21.0, 26.2, "Elimizde iki dik açı var: m(^ELF^) = 90° ve m(^DLK^) = 90°. Gri bölge ikisinin ortak parçası, yani ^KLE^ açısı."),
    (26.2, 30.0, "Ortak parçayı ikisinden de çıkarınca geriye kalanlar eşit olur: *m(^FLK^) = m(^ELD^) = x*"),
    (30.0, 36.8, "LED ve LFK dik üçgenlerinde hipotenüsler eşit (|LD| = |LK|), x açıları da eşit. LED'yi L etrafında 90° çevirince LFK'nin üstüne tam oturuyor."),
    (36.8, 41.0, "İki üçgen eş olduğuna göre karşılıklı kenarlar da eşit: *|LE| = |LF|*"),
    (41.0, 48.0, "Demek ki L, [AD] ve [AB] kenarlarına eşit uzaklıkta. Bir açının kollarına eşit uzaklıktaki nokta açıortay üzerindedir. A açısının açıortayı da *[AC] köşegeni*."),
    (48.0, 55.5, "L köşegenin üzerinde, o halde [LC] de köşegenin bir parçası. Köşegen C açısını ikiye böler: *α = m(^ACB^) = 45°*"),
    (55.5, 99.0, "Merak edenler için: K'yi [AB] üzerinde nereye kaydırırsak kaydıralım L köşegenden ayrılmıyor. *α hep 45°.*"),
]

K0 = 0.2

def kval(t):
    if t < 56.5:
        return K0
    u = min(1.0, (t - 56.5) / 7.5)
    return K0 + 0.4 * (1 - math.cos(2 * math.pi * u)) / 2

def frame(fi):
    t = fi / FPS
    img = Image.new("RGB", (W * SS, H * SS), BG)
    d = ImageDraw.Draw(img, "RGBA")
    k = kval(t)
    g = geo(k)
    A, B, C, D, K, L, E, F = (g[n] for n in "ABCDKLEF")

    # header
    a = vis(t, 0.0)
    rrect(d, (60, 70, 260, 128), 29, rgba(RED, a))
    text_at(d, (160, 99), "21. SORU", 30, (255, 255, 255), a, bold=True)
    y = 205
    a = vis(t, 0.4)
    y = rich_block(d, "ABCD kare,  [DL] ⊥ [LK],  |DL| = |LK|", 60, y, 960, 40, INK, RED, a)
    a = vis(t, 0.8)
    y = rich_block(d, "Buna göre *α = m(^LCB^)* kaç derecedir?", 60, y + 10, 960, 40, INK, RED, a, bold=True)
    a = vis(t, 1.1)
    text_at(d, (60, y + 18), "A) 30    B) 37,5    C) 45    D) 52,5    E) 62,5", 34, GRAY, a, anchor="ls")
    if t > 51.5:
        # highlight correct choice
        a = vis(t, 51.5)
        f = font(34)
        x0 = 60 + f.getlength("A) 30    B) 37,5    ") / SS
        x1 = x0 + f.getlength("C) 45") / SS
        d.rounded_rectangle([(x0 - 12) * SS, (y + 18 - 38) * SS, (x1 + 12) * SS, (y + 18 + 12) * SS],
                            radius=12 * SS, outline=rgba(GREEN, a), width=4 * SS)

    # fills (under lines)
    tri_a = vis(t, 9.0) * (1 - 0.6 * prog(t, 30.0, 31.0) + 0.6 * prog(t, 55.5, 56.3))
    poly(d, [D, L, K], BLUE, 0.16 * tri_a)
    sq_a = vis(t, 17.5, 21.0)
    poly(d, [A, E, L, F], ORANGE, 0.10 * sq_a)

    # step 4: angle chase at L
    aLD, aLK, aLE, aLF = ang(L, D), ang(L, K), ang(L, E), ang(L, F)
    s1 = vis(t, 21.5, 26.2)
    sector(d, L, 120, aLF, aLE, ORANGE, 0.28 * s1)
    s2 = vis(t, 23.2, 26.2)
    sector(d, L, 120, aLK, aLD + 360 if aLD < aLK else aLD, BLUE, 0.22 * s2)
    s3 = vis(t, 24.8, 26.2)
    sector(d, L, 120, aLK, aLE, GRAY, 0.30 * s3)
    xa = vis(t, 26.2, 55.5)
    sector(d, L, 85, aLF, aLK, GREEN, 0.35 * xa)
    sector(d, L, 85, aLE, aLD + 360 if aLD < aLE else aLD, GREEN, 0.35 * xa)
    arc(d, L, 85, aLF, aLK, GREEN, 3, xa)
    arc(d, L, 85, aLE, aLD + 360 if aLD < aLE else aLD, GREEN, 3, xa)

    # step 5: congruent triangles
    ca = vis(t, 30.3, 55.5)
    poly(d, [L, E, D], GREEN, 0.22 * ca)
    poly(d, [L, F, K], GREEN, 0.22 * ca)
    rot = prog(t, 33.0, 36.5)
    ra = vis(t, 32.6) * (1 - prog(t, 38.0, 39.0))
    if ra > 0:
        th = -math.pi / 2 * rot
        def R(p):
            vx, vy = p[0] - L[0], p[1] - L[1]
            return (L[0] + vx * math.cos(th) - vy * math.sin(th), L[1] + vx * math.sin(th) + vy * math.cos(th))
        pts = [L, R(E), R(D)]
        poly(d, pts, GREEN, 0.45 * ra)
        for i in range(3):
            seg(d, pts[i], pts[(i + 1) % 3], GREEN, 4, ra)

    # square
    for i, (p, q) in enumerate([(A, B), (B, C), (C, D), (D, A)]):
        seg(d, p, q, INK, 5, 1, prog(t, 0.4 + i * 0.4, 0.9 + i * 0.4))

    # diagonal AC
    dg = prog(t, 41.5, 43.5)
    dashed(d, A, C, PURPLE, 5, vis(t, 41.5), dg)
    a45 = vis(t, 43.3)
    arc(d, A, 70, -90, -45, PURPLE, 4, a45)
    arc(d, A, 82, -45, 0, PURPLE, 4, a45)
    text_at(d, (P(A)[0] + 52, P(A)[1] + 125), "45°", 28, PURPLE, a45, bold=True)
    text_at(d, (P(A)[0] + 125, P(A)[1] + 48), "45°", 28, PURPLE, a45, bold=True)

    # perpendiculars
    pe = vis(t, 14.6, 55.6)
    dashed(d, L, E, ORANGE, 4, pe, prog(t, 14.6, 15.8))
    pf = vis(t, 15.6, 55.6)
    dashed(d, L, F, ORANGE, 4, pf, prog(t, 15.6, 16.8))
    right_mark(d, E, L, D, ORANGE, 22, 3, vis(t, 16.6, 55.6))
    right_mark(d, F, L, K, ORANGE, 22, 3, vis(t, 16.9, 55.6))
    eq = vis(t, 37.0, 55.6)
    ticks(d, L, E, 3, GREEN, eq, size=11, w=3, gap=8)
    ticks(d, L, F, 3, GREEN, eq, size=11, w=3, gap=8)

    # main figure segments
    seg(d, D, L, BLUE, 5, 1, prog(t, 3.4, 4.6))
    seg(d, L, K, BLUE, 5, 1, prog(t, 4.6, 5.6))
    seg(d, L, C, INK, 4, 1, prog(t, 5.8, 6.8))
    right_mark(d, L, D, K, BLUE, 24, 3, vis(t, 5.6))
    ticks(d, D, L, 2, BLUE, vis(t, 6.0))
    ticks(d, L, K, 2, BLUE, vis(t, 6.0))

    # alpha at C
    aa = vis(t, 7.0)
    hl = prog(t, 49.5, 50.5)
    acol = RED
    sector(d, C, 95, 90, 135, RED, (0.10 + 0.18 * hl) * aa)
    arc(d, C, 95, 90, 135, acol, 4, aa)
    am = (math.cos(math.radians(112.5)), math.sin(math.radians(112.5)))
    cx, cy = P(C)
    q_a = aa * (1 - prog(t, 50.0, 50.5))
    text_at(d, (cx + am[0] * 128, cy - am[1] * 128), "α", 40, RED, q_a, bold=True)
    v_a = vis(t, 50.4)
    text_at(d, (cx + am[0] * 132, cy - am[1] * 132), "45°", 32, RED, v_a, bold=True)

    # points + labels
    dot(d, K, INK, 8, vis(t, 3.0))
    dot(d, L, INK, 8, vis(t, 4.4))
    sa = vis(t, 2.4)
    label(d, A, "A", (-30, -30), alpha=sa)
    label(d, B, "B", (30, -30), alpha=sa)
    label(d, C, "C", (30, 32), alpha=sa)
    label(d, D, "D", (-30, 32), alpha=sa)
    label(d, K, "K", (0, -38), alpha=vis(t, 3.0))
    label(d, L, "L", (34, -6), alpha=vis(t, 4.4))
    dot(d, E, ORANGE, 7, pe)
    dot(d, F, ORANGE, 7, pf)
    label(d, E, "E", (-34, 0), ORANGE, vis(t, 15.4, 55.6))
    label(d, F, "F", (0, -38), ORANGE, vis(t, 16.4, 55.6))
    lx = vis(t, 26.6, 55.5)
    for a0, a1 in ((aLF, aLK), (aLE, aLD + 360 if aLD < aLE else aLD)):
        m = math.radians((a0 + a1) / 2)
        px, py = P(L)
        text_at(d, (px + math.cos(m) * 112, py - math.sin(m) * 112), "x", 32, GREEN, lx, bold=True)

    # caption box
    rrect(d, (40, 1420, 1040, 1800), 30, rgba((255, 255, 255), 1), outline=rgba((225, 218, 205), 1), w=2)
    for i, (t0, t1, s) in enumerate(CAPS):
        a = vis(t, t0, t1, 0.35)
        if a <= 0:
            continue
        text_at(d, (85, 1478), f"{i + 1}/{len(CAPS)}", 26, GRAY, a, bold=True, anchor="ls")
        rich_block(d, s, 85, 1540, 910, 38, INK, RED, a, lh=1.42)

    # answer badge
    ab = vis(t, 51.5)
    if ab > 0:
        rrect(d, (700, 70, 1020, 128), 29, rgba(GREEN, ab))
        text_at(d, (860, 99), "Cevap: C) 45", 30, (255, 255, 255), ab, bold=True)

    img = img.resize((W, H), Image.LANCZOS)
    return img.tobytes()

if __name__ == "__main__":
    out = sys.argv[1]
    if len(sys.argv) > 2 and sys.argv[2] == "still":
        for ts in map(float, sys.argv[3:]):
            Image.frombytes("RGB", (W, H), frame(int(ts * FPS))).save(f"{out}_{ts:05.1f}.png")
        sys.exit()
    n = int(DUR * FPS)
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                           "-movflags", "+faststart", out], stdin=subprocess.PIPE)
    with Pool(4) as pool:
        for i, b in enumerate(pool.imap(frame, range(n), chunksize=8)):
            ff.stdin.write(b)
            if i % 300 == 0:
                print(i, "/", n, flush=True)
    ff.stdin.close()
    ff.wait()
