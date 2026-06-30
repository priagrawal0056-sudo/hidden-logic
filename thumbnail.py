"""
thumbnail.py - MrBeast-shock style thumbnails: ONE giant focal hook word with a blown-out
neon glow, a punchy high-contrast grade on a dramatic topic photo, a small subject tag, and
the Hidden Logic badge. Mobile-first: the focal word is readable at feed size. Built with
Pillow. (Note: Shorts use an auto-grabbed first frame in-feed; this thumbnail shows in
search/channel-grid surfaces.)

Entry: make_thumbnail(base_image_path, out_path, title)
"""
import os
import platform
import re

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

W, H = 1080, 1920
GOLD = (255, 209, 64)
YELLOW = (255, 238, 88)
CYAN = (34, 226, 255)
RED = (255, 40, 64)
WHITE = (255, 255, 255)


def _font(size):
    cands = []
    s = platform.system()
    if s == "Windows":
        cands = [r"C:\Windows\Fonts\impact.ttf", r"C:\Windows\Fonts\ariblk.ttf",
                 r"C:\Windows\Fonts\arialbd.ttf"]
    elif s == "Darwin":
        cands = ["/Library/Fonts/Impact.ttf", "/System/Library/Fonts/Supplemental/Impact.ttf",
                 "/System/Library/Fonts/Supplemental/Arial Bold.ttf"]
    else:
        cands = ["/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
    for c in cands:
        if os.path.exists(c):
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _clean(s):
    s = re.sub(r"\s*#.*$", "", s)
    return re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]", "", s).strip()


def _coherent_phrase(after: str) -> str:
    """Extract a SHORT, COHERENT, CLICKBAITY phrase from the title's curiosity part that
    reads as a complete idea on a thumbnail - never a dangling fragment like 'DAY QUIT'.
    Prefers the most DRAMATIC noun (not just the last), and pulls a 1-2 word phrase that
    reads as a hook. Returns '' if nothing sensible can be formed."""
    # high-drama end-words, ranked: tier-1 words are the most clickbaity
    TIER1 = {"war","record","curse","scandal","disaster","collapse","miracle","revenge",
             "heartbreak","drought","ban","betrayal","trap","robbery","exit","shootout",
             "retirement","comeback","blunder","upset","penalty","penalties","redcard"}
    TIER2 = {"title","goal","goals","final","finals","card","cards","trophy","cup",
             "league","vote","seat","camera","bench","debut","champion","champions",
             "winner","save","saves","header","mistake","strike","hattrick","treble",
             "season","seasons","minute","minutes","second","seconds","game","games",
             "streak"}
    WEAK = {"day","win","quit","against","nation","person","who","the","a","an","of",
            "to","in","on","and","but","his","her","that","this","with","from","he",
            "she","they","it","still","just","only","cared","about","made","make","was",
            "were","reigning","world","one","ever","always","never"}
    words = re.findall(r"[A-Za-z]+", after)
    if not words:
        return ""
    low = [w.lower() for w in words]
    # dramatic ACTION/STATE words also make great standalone hooks (quit, banned, out...)
    ACTION = {"quit","banned","retired","benched","robbed","cheated","destroyed",
              "humiliated","betrayed","collapsed","vanished","walked","refused","out",
              "snubbed","dropped","ejected","sacked","fired"}
    for i, w in enumerate(low):
        if w in ACTION:
            # phrase it with a following object if short ("QUIT ARGENTINA", "WALKED OUT")
            if i + 1 < len(low) and low[i + 1] not in WEAK and len(words[i + 1]) >= 3 \
                    and low[i + 1] not in ("on", "in", "at"):
                return (words[i] + " " + words[i + 1]).upper()
            return words[i].upper()
    # pick the best end-noun: prefer a tier-1 dramatic word anywhere; else last tier-2
    end_idx = None
    for i, w in enumerate(low):
        if w in TIER1:
            end_idx = i  # take the first tier-1 (usually the punchiest)
            break
    if end_idx is None:
        for i in range(len(low) - 1, -1, -1):
            if low[i] in TIER2:
                end_idx = i
                break
    if end_idx is None:
        return ""
    start = end_idx
    # prepend one descriptive word for a richer phrase ("POSSESSION TRAP", "GOAL DROUGHT")
    if end_idx - 1 >= 0 and low[end_idx - 1] not in WEAK and len(words[end_idx - 1]) >= 3:
        start = end_idx - 1
    phrase = " ".join(words[start:end_idx + 1]).upper()
    if all(w.lower() in WEAK for w in phrase.split()) or len(phrase) < 4:
        return ""
    return phrase


def _focal_and_tag(title: str):
    """Return (FOCAL big shock phrase, small subject tag). Focal is short and
    punchy - the curiosity bomb. Tag is the subject for context."""
    clean_title = _clean(title)
    
    # 1) Map keywords to specific high-contrast focal hooks
    mappings = [
        (["casino"], "NO CLOCKS", "CASINO DESIGN"),
        (["hotel"], "UNCANNY ROOM", "HOTEL SECRETS"),
        (["airport", "boarding", "flight"], "STRESS TRAP", "AIRPORT FLOW"),
        (["supermarket", "grocery", "store", "shop", "dairy", "milk", "vegetable"], "TIME TRAP", "STORE LAYOUT"),
        (["ikea"], "ONE WAY", "IKEA FLOW"),
        (["elevator"], "MIRROR TRICK", "ELEVATOR DESIGN"),
        (["traffic", "lane", "merge", "merging", "road"], "SLOW LANE", "TRAFFIC FLOW"),
        (["alarm", "snooze", "waking", "wake"], "BRAIN GLITCH", "SLEEP SCIENCE"),
        (["phone", "app", "netflix", "notification", "vibrate"], "SCREEN TRAP", "DIGITAL TRICKS"),
        (["doorway", "forget", "room"], "BRAIN GLITCH", "HUMAN BRAIN"),
        (["menu", "price", "prices", "9.99"], "9.99 TRICK", "PRICING DESIGN"),
        (["toilet", "restroom"], "DESIGN FLAW", "BATHROOM DESIGN"),
        (["vending"], "COIN TRAP", "VENDING DESIGN")
    ]
    
    title_lower = clean_title.lower()
    for keywords, focal_hook, default_tag in mappings:
        if any(kw in title_lower for kw in keywords):
            return focal_hook, default_tag
            
    # Fallback/last resort: try to find any colon/dash split
    subject = _clean(title.split(":")[0]) if ":" in title else _clean(title)
    after = _clean(title.split(":", 1)[1]) if ":" in title else ""
    
    focal = ""
    if after:
        # try to get a coherent phrase from after
        focal = _coherent_phrase(after)
        
    if not focal:
        # Default fallback when no keywords match and no colon is present
        # We can split the title, take the first 2-3 words of the main action
        words = clean_title.split()
        # Skip "Why", "You", "Always", "How", "It", "Feels", "To", "Is", "The", "A", "An"
        fillers = {"why", "you", "always", "how", "it", "feels", "to", "is", "the", "a", "an", "never", "so"}
        meaningful = [w for w in words if w.lower() not in fillers]
        if len(meaningful) >= 2:
            focal = " ".join(meaningful[:2]).upper()
        elif meaningful:
            focal = meaningful[0].upper()
        else:
            focal = "DESIGN TRICK"
            
    tag = subject.upper()
    if len(tag) > 22:
        tag = tag[:22]
    # NEVER let the giant focal just repeat the tag (kills the curiosity gap).
    # If they collide, the focal wins as the scroll-stopper and we drop the tag.
    if focal.replace(" ", "") == tag.replace(" ", ""):
        tag = ""
    return focal, tag


def _fit_cover(img):
    img = img.convert("RGB")
    scale = max(W / img.width, H / img.height)
    img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    x = (img.width - W) // 2
    y = (img.height - H) // 2
    return img.crop((x, y, x + W, y + H))


def _punch_grade(img):
    """High-contrast, high-saturation MrBeast grade."""
    img = ImageEnhance.Contrast(img).enhance(1.18)
    img = ImageEnhance.Color(img).enhance(1.45)
    img = ImageEnhance.Brightness(img).enhance(1.02)
    return img


def _wrap(text, max_chars):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 <= max_chars or not cur:
            cur = (cur + " " + w).strip()
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines[:2]  # never more than 2 lines for the focal


def _draw_focal(base, lines, color):
    """Giant centered focal text with a huge soft glow + thick black stroke."""
    # size to fit the widest line within ~1000px, target very large
    size = 360
    while size > 120:
        f = _font(size)
        d = ImageDraw.Draw(base)
        widest = max(d.textbbox((0, 0), l, font=f, stroke_width=14)[2] for l in lines)
        tallest = sum(d.textbbox((0, 0), l, font=f, stroke_width=14)[3] for l in lines)
        if widest <= 1010 and tallest <= 1000:
            break
        size -= 12
    f = _font(size)
    d = ImageDraw.Draw(base)
    line_h = max(d.textbbox((0, 0), l, font=f, stroke_width=14)[3] for l in lines) + 10
    total_h = line_h * len(lines)
    y0 = (H - total_h) // 2 + 120  # slightly below center, leaves room for tag above

    # glow layer (color blow-out)
    glow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for i, ln in enumerate(lines):
        w = d.textbbox((0, 0), ln, font=f)[2]
        x = (W - w) // 2
        y = y0 + i * line_h
        gd.text((x, y), ln, font=f, fill=(*color, 255),
                stroke_width=26, stroke_fill=(*color, 255))
    glow = glow.filter(ImageFilter.GaussianBlur(34))
    base.alpha_composite(glow)
    base.alpha_composite(glow)  # double for intensity

    # crisp text: white fill, heavy black stroke
    for i, ln in enumerate(lines):
        w = d.textbbox((0, 0), ln, font=f)[2]
        x = (W - w) // 2
        y = y0 + i * line_h
        d.text((x, y), ln, font=f, fill=WHITE, stroke_width=14, stroke_fill=(0, 0, 0))
    return y0, total_h


def _make_gradient_bg():
    """A brand-neutral dark gradient, used when no usable photo/frame exists so the thumbnail
    is NEVER black. Deep indigo -> near-black: on-brand for the 'hidden systems / psychology'
    look and makes the focal word pop (replaces the old football-pitch green)."""
    import math
    base = Image.new("RGB", (W, H))
    px = base.load()
    # two-stop vertical gradient (deep indigo -> near-black)
    c0 = (38, 28, 64)     # deep indigo
    c1 = (10, 12, 24)     # near-black blue
    for y in range(0, H, 2):
        t = y / H
        r = int(c0[0] + (c1[0] - c0[0]) * t)
        g = int(c0[1] + (c1[1] - c0[1]) * t)
        b = int(c0[2] + (c1[2] - c0[2]) * t)
        for yy in (y, min(y + 1, H - 1)):
            for x in range(0, W, 2):
                px[x, yy] = (r, g, b)
                if x + 1 < W:
                    px[x + 1, yy] = (r, g, b)
    return base


def _is_unusable(img) -> bool:
    """True if the image is effectively black/blank (failed grab or dark video frame),
    so the caller swaps in the gradient instead of rendering text on black."""
    try:
        small = img.convert("RGB").resize((32, 32))
        pixels = list(small.getdata())
        avg = sum(sum(p) for p in pixels) / (len(pixels) * 3)
        return avg < 22  # very dark on average = unusable
    except Exception:
        return True


def make_thumbnail(base_image_path: str, out_path: str, title: str):
    # load the base photo/frame; if it's missing OR effectively black, use a vibrant
    # gradient so the thumbnail is NEVER a black screen.
    try:
        src = Image.open(base_image_path)
        src.load()
        if _is_unusable(src):
            src = _make_gradient_bg()
    except Exception:
        src = _make_gradient_bg()
    base = _punch_grade(_fit_cover(src)).convert("RGBA")

    # overall dark veil so text pops off the photo (user wanted it darker)
    veil = Image.new("RGBA", (W, H), (0, 0, 0, 95))
    base.alpha_composite(veil)
    # darken edges so center text pops (radial-ish: darken top and bottom bands)
    dark = Image.new("L", (1, H), 0)
    for y in range(H):
        d = 0
        if y < H * 0.30:
            d = int((1 - y / (H * 0.30)) * 120)
        elif y > H * 0.70:
            d = int(((y - H * 0.70) / (H * 0.30)) * 150)
        dark.putpixel((0, y), min(255, d))
    dark = dark.resize((W, H))
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 255)); shade.putalpha(dark)
    base.alpha_composite(shade)

    focal, tag = _focal_and_tag(title)
    # pick a shock color for the focal: yellow default, red for scorelines/negatives
    color = YELLOW
    if re.search(r"\d+\s*[-\u2013]\s*\d+", focal) or any(
            w in focal for w in ("WAR", "BANNED", "WORST", "SCANDAL", "CURSE", "LOST")):
        color = RED
    lines = _wrap(focal, 9)
    _draw_focal(base, lines, color)

    # subject tag: a bold colored pill near the top, white text (context, small)
    d = ImageDraw.Draw(base)
    if tag:
      tf = _font(72)
      tb = d.textbbox((0, 0), tag, font=tf)
      tw, th = tb[2] - tb[0], tb[3] - tb[1]
      px, py = 40, 28
      bx0 = (W - (tw + px * 2)) // 2
      by0 = int(H * 0.20)
      d.rounded_rectangle([bx0, by0, bx0 + tw + px * 2, by0 + th + py * 2],
                          radius=26, fill=(0, 0, 0, 180))
      d.rounded_rectangle([bx0, by0, bx0 + 14, by0 + th + py * 2], radius=6, fill=CYAN)
      d.text((bx0 + px + 8, by0 + py - 6), tag, font=tf, fill=WHITE,
             stroke_width=3, stroke_fill=(0, 0, 0))

    # Hidden Logic badge bottom-left (out of the duration-badge zone on the right)
    bf = _font(56)
    bb = d.textbbox((0, 0), "Hidden Logic", font=bf)
    bw, bh = bb[2] - bb[0], bb[3] - bb[1]
    d.rounded_rectangle([46, H - 130, 46 + bw + 56, H - 130 + bh + 40],
                        radius=18, fill=GOLD)
    d.text((74, H - 130 + 14), "Hidden Logic", font=bf, fill=(12, 12, 12))

    base.convert("RGB").save(out_path, "JPEG", quality=90)
