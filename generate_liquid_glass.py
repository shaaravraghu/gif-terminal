# generate_liquid_glass.py
import gifos
import os
import glob
import qrcode
from PIL import Image, ImageFilter, ImageDraw, ImageChops
from pathlib import Path
from gifos.utils.convert_ansi_escape import ConvertAnsiEscape

# ============================================
# Optional: fetch fresh GitHub stats before building the GIF
# ============================================
# Runs fetch_github_stats.py in-process so a single `python gif_script.py`
# (e.g. one CI step in GitHub Actions) produces an up-to-date
# assets/github_stats.json before the "$ contrib_stats" terminal section
# reads it further down.
#
# Controlled entirely by env vars so local runs without a token still work:
#   GITHUB_TOKEN      - a PAT (see fetch_github_stats.py docstring for scopes)
#   GITHUB_USERNAME    - the account to report on
#   SKIP_STATS_FETCH   - set to "1" to skip this step even if a token is set
#
# If the token/username aren't set, or the fetch fails for any reason
# (rate limit, network hiccup, etc.), this prints a warning and moves on —
# it never aborts the GIF build. Whatever assets/github_stats.json already
# exists on disk (or doesn't) is what the contrib_stats section will use.
if os.environ.get("SKIP_STATS_FETCH") == "1":
    print("INFO: SKIP_STATS_FETCH=1 set, skipping GitHub stats fetch.")
elif os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_USERNAME"):
    try:
        import fetch_github_stats
        print("INFO: fetching fresh GitHub stats before building the GIF...")
        fetch_github_stats.main()
    except Exception as e:
        print(
            f"WARNING: GitHub stats fetch failed ({type(e).__name__}: {e}). "
            "Continuing without fresh stats — the contrib_stats section will "
            "fall back to any existing assets/github_stats.json, or be "
            "skipped if none exists."
        )
else:
    print(
        "INFO: GITHUB_TOKEN / GITHUB_USERNAME not set — skipping GitHub "
        "stats fetch. The contrib_stats section will be skipped unless "
        "assets/github_stats.json already exists on disk."
    )

# Override with high-contrast colors for blue glass background.
# Avoid cyan/blue tones — they blend with the wallpaper.
ConvertAnsiEscape.ANSI_ESCAPE_MAP_TXT_COLOR.update({
    "39": "#FFFFFF",   # default fg → pure white
    "31": "#FF3355",   # red
    "32": "#00FF88",   # neon green
    "33": "#FFE500",   # pure yellow
    "34": "#FF9500",   # orange (blue would blend)
    "35": "#FF44DD",   # magenta
    "36": "#FFFFFF",   # cyan → white (cyan blends with wallpaper)
    "37": "#FFFFFF",   # white
    "91": "#FF3355",   # bright red
    "92": "#00FF88",   # bright neon green
    "93": "#FFE500",   # bright yellow
    "94": "#FF9500",   # bright orange
    "95": "#FF44DD",   # bright magenta
    "96": "#FFE500",   # bright cyan → yellow
    "97": "#FFFFFF",   # bright white
})

# ============================================
# Liquid Glass Theme — macOS-style terminal
# ============================================
#
# REQUIREMENTS:
# 1. assets/Aurora.png must be present
# 2. assets/SKILLS.png must be present
# 3. Python dependencies: gifos, Pillow, qrcode
#
# APPROACH:
# gifos generates terminal frames with the default background (#0c0e0f).
# Before assembling the GIF, each PNG frame is post-processed:
#   - wallpaper fills the GIF canvas
#   - frosted glass covers the terminal window
#   - terminal content is composited using chroma-key
#   - macOS chrome is drawn on top
# ============================================

# ---- Layout constants ----
GIF_W, GIF_H = 740, 520
WIN_X, WIN_Y = 1, 1
WIN_W = 738
TITLE_H = 30
WIN_H = TITLE_H + 480
TERMINAL_X = WIN_X
TERMINAL_Y = WIN_Y + TITLE_H
CORNER_RADIUS = 10

# Default gifos background color (ANSI code 49 → #0c0e0f) — used as chroma key
BG_COLOR_HEX = "#0c0e0f"
BG_COLOR = (12, 14, 15)

# gifos defaults to 15 FPS in the package configuration.
# This keeps the README-requested 5-second SKILLS hold at exactly 75 frames.
GIFOS_FPS = 15
SKILLS_HOLD_SECONDS = 10
SKILLS_HOLD_FRAMES = GIFOS_FPS * SKILLS_HOLD_SECONDS

FRAMES_DIR = "./frames"
WALLPAPER_PATH = "assets/Aurora.png"
SKILLS_PATH = "assets/SKILLS.png"
QR_PATH = "./clipwallet_qr.png"
OUTPUT_GIF = "output.gif"
CLIPWALLET_URL = "https://github.com/shaaravraghu/ClipWallet/"


# ============================================
# Liquid Glass helpers
# ============================================

def _scale_crop(img, target_w, target_h):
    """Scale image to fill target dimensions while preserving aspect ratio."""
    w, h = img.size
    ratio = w / h
    target_ratio = target_w / target_h

    if ratio > target_ratio:
        new_h = target_h
        new_w = int(new_h * ratio)
    else:
        new_w = target_w
        new_h = int(new_w / ratio)

    scaled = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return scaled.crop((left, top, left + target_w, top + target_h))


def _blend_overlay(base_rgb, overlay_rgba):
    """Alpha-composite an RGBA overlay onto an RGB base."""
    result = Image.alpha_composite(base_rgb.convert("RGBA"), overlay_rgba)
    return result.convert("RGB")


def prepare_glass_layers(wallpaper_path):
    """
    Build the static base canvas and chrome overlay used for every frame.

    Returns:
        base_canvas — RGB image (GIF_W × GIF_H)
        chrome      — RGBA image (GIF_W × GIF_H)
    """
    wallpaper = Image.open(wallpaper_path).convert("RGB")
    wallpaper_bg = _scale_crop(wallpaper, GIF_W, GIF_H)

    # ---- Drop shadow ----
    shadow = Image.new("RGBA", (GIF_W, GIF_H), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        [(WIN_X + 4, WIN_Y + 6), (WIN_X + WIN_W + 3, WIN_Y + WIN_H + 5)],
        radius=CORNER_RADIUS,
        fill=(0, 0, 0, 130),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=8))
    wallpaper_with_shadow = _blend_overlay(wallpaper_bg, shadow)

    # ---- Frosted glass — title bar ----
    title_region = wallpaper_bg.crop(
        (WIN_X, WIN_Y, WIN_X + WIN_W, WIN_Y + TITLE_H)
    )
    frosted_title = title_region.filter(ImageFilter.GaussianBlur(radius=5))
    title_overlay = Image.new("RGBA", frosted_title.size, (255, 255, 255, 30))
    frosted_title = _blend_overlay(frosted_title, title_overlay)

    # ---- Frosted glass — content area ----
    content_region = wallpaper_bg.crop(
        (TERMINAL_X, TERMINAL_Y, TERMINAL_X + WIN_W, TERMINAL_Y + 450)
    )
    frosted_content = content_region.filter(ImageFilter.GaussianBlur(radius=4))
    content_overlay = Image.new("RGBA", frosted_content.size, (255, 255, 255, 1))
    frosted_content = _blend_overlay(frosted_content, content_overlay)

    # ---- Assemble frosted window ----
    window_img = Image.new("RGB", (WIN_W, WIN_H))
    window_img.paste(frosted_title, (0, 0))
    window_img.paste(frosted_content, (0, TITLE_H))

    window_mask = Image.new("L", (WIN_W, WIN_H), 0)
    ImageDraw.Draw(window_mask).rounded_rectangle(
        [(0, 0), (WIN_W - 1, WIN_H - 1)],
        radius=CORNER_RADIUS,
        fill=255,
    )

    # ---- Composite window onto wallpaper ----
    base_canvas = wallpaper_with_shadow.copy()
    base_canvas.paste(window_img, (WIN_X, WIN_Y), window_mask)

    # ---- Chrome overlay ----
    chrome = Image.new("RGBA", (GIF_W, GIF_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(chrome)

    draw.rounded_rectangle(
        [(WIN_X, WIN_Y), (WIN_X + WIN_W - 1, WIN_Y + WIN_H - 1)],
        radius=CORNER_RADIUS,
        outline=(255, 255, 255, 55),
        width=1,
    )

    draw.line(
        [
            (WIN_X + CORNER_RADIUS, WIN_Y + TITLE_H),
            (WIN_X + WIN_W - CORNER_RADIUS, WIN_Y + TITLE_H),
        ],
        fill=(255, 255, 255, 35),
        width=1,
    )

    traffic_lights = [
        ("#FF5F57", "#E0443E"),
        ("#FFBD2E", "#DFA223"),
        ("#28C840", "#1DAD2B"),
    ]
    tl_r = 6
    tl_y = WIN_Y + TITLE_H // 2

    for i, (fill, outline) in enumerate(traffic_lights):
        cx = WIN_X + 15 + i * 20 + tl_r
        draw.ellipse(
            [(cx - tl_r, tl_y - tl_r), (cx + tl_r, tl_y + tl_r)],
            fill=fill,
            outline=outline,
        )

    return base_canvas, chrome


def chroma_mask(terminal_frame):
    """
    Return an L mask where:
      255 = terminal pixel
        0 = terminal background / show glass
    """
    bg_ref = Image.new("RGB", terminal_frame.size, BG_COLOR)
    diff = ImageChops.difference(terminal_frame, bg_ref)
    r, g, b = diff.split()
    mask = ImageChops.lighter(ImageChops.lighter(r, g), b)
    return mask.point(lambda p: 255 if p > 0 else 0)


def _frame_number(frame_path):
    return int(
        os.path.splitext(os.path.basename(frame_path))[0].split("_")[1]
    )


def get_frame_files():
    return sorted(
        glob.glob(f"{FRAMES_DIR}/frame_*.png"),
        key=_frame_number,
    )


def post_process_frames(base_canvas, chrome, frames_dir=FRAMES_DIR):
    """Composite the liquid-glass effect onto every gifos-generated PNG frame."""
    frame_files = sorted(
        glob.glob(f"{frames_dir}/frame_*.png"),
        key=_frame_number,
    )

    print(
        f"INFO: Post-processing {len(frame_files)} frames "
        "with liquid glass effect..."
    )

    for frame_path in frame_files:
        terminal_frame = Image.open(frame_path).convert("RGB")
        canvas = base_canvas.copy()

        mask = chroma_mask(terminal_frame)
        canvas.paste(terminal_frame, (TERMINAL_X, TERMINAL_Y), mask)

        canvas = Image.alpha_composite(
            canvas.convert("RGBA"), chrome
        ).convert("RGB")

        canvas.save(frame_path, "PNG")

    print(
        f"INFO: Liquid glass post-processing complete ({len(frame_files)} frames)."
    )


# ============================================
# Special visual frames
# ============================================

def _fit_inside(img, max_w, max_h):
    """Return a resized copy fitting inside max_w × max_h."""
    result = img.copy()
    result.thumbnail((max_w, max_h), Image.LANCZOS)
    return result


def create_qr_code(url, path=QR_PATH):
    """Create the ClipWallet QR image used by the final terminal frame."""
    try:
        import qrcode
    except ImportError as exc:
        raise RuntimeError(
            "The qrcode package is required. Install it with: pip install qrcode[pil]"
        ) from exc

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGBA")
    qr_img.save(path)
    return path


def patch_latest_frames_with_image(image_path, frame_count, max_w=620, max_h=330):
    """
    Replace the terminal-area content of the latest N raw gifos frames with an image.
    The frames remain PNGs and are still passed through the existing liquid-glass
    post-processing afterwards.
    """
    frame_files = get_frame_files()
    if not frame_files:
        raise RuntimeError("No gifos frames were generated before image insertion.")

    target_frames = frame_files[-frame_count:]
    source = Image.open(image_path).convert("RGBA")
    source = _fit_inside(source, max_w=max_w, max_h=max_h)

    # A lightly translucent panel keeps the image legible without changing
    # the surrounding macOS liquid-glass treatment.
    panel_w = min(WIN_W - 36, source.width + 28)
    panel_h = min(410, source.height + 28)
    panel = Image.new("RGBA", (panel_w, panel_h), (255, 255, 255, 215))

    x = (panel_w - source.width) // 2
    y = (panel_h - source.height) // 2
    panel.alpha_composite(source, (x, y))

    px = (WIN_W - panel.width) // 2
    py = TITLE_H + 18 + max(0, (450 - panel.height) // 2)

    for frame_path in target_frames:
        frame = Image.open(frame_path).convert("RGBA")
        frame.alpha_composite(panel, (px, py))
        frame.convert("RGB").save(frame_path, "PNG")


def patch_latest_frames_with_qr(qr_path, frame_count):
    """Add a readable QR code to the latest terminal frames."""
    frame_files = get_frame_files()
    if not frame_files:
        raise RuntimeError("No gifos frames were generated before QR insertion.")

    target_frames = frame_files[-frame_count:]
    qr = Image.open(qr_path).convert("RGBA")
    qr = _fit_inside(qr, max_w=190, max_h=190)

    for frame_path in target_frames:
        frame = Image.open(frame_path).convert("RGBA")

        # Local frame coordinates (WIN_W x 450) — no TERMINAL_Y offset here.
        x = WIN_W - qr.width - 30
        y = 450 - qr.height - 30

        backing = Image.new("RGBA", (qr.width + 12, qr.height + 12), "white")
        backing.alpha_composite(qr, (6, 6))

        frame.alpha_composite(backing, (x - 6, y - 6))
        frame.convert("RGB").save(frame_path, "PNG")


# ============================================
# Terminal — exact README_TERMINAL.txt sequence
# ============================================

# IMPORTANT:
# The content/order below follows README_TERMINAL.txt exactly.
# The README itself is never modified by this script.

t = gifos.Terminal(width=WIN_W, height=450, xpad=10, ypad=10)
t.set_prompt("$ ")

t = gifos.Terminal(width=WIN_W, height=450, xpad=10, ypad=10)
t.set_prompt("$ ")

# --------------------------------------------
# Sanitize text for the gohufont-uni-14 bitmap font, which only
# supports Latin-1 (0–255). Smart/typographic Unicode punctuation
# (curly quotes, em/en dashes, ellipsis, non-breaking space, etc.)
# gets normalized to ASCII equivalents before rendering.
# --------------------------------------------
_ASCII_REPLACEMENTS = {
    "\u2018": "'", "\u2019": "'",   # ' '
    "\u201c": '"', "\u201d": '"',  # " "
    "\u2013": "-", "\u2014": "-",  # – —
    "\u2026": "...",                # …
    "\u00a0": " ",                  # non-breaking space
}

def _sanitize_text(text):
    if not isinstance(text, str):
        return text
    for uni, ascii_ in _ASCII_REPLACEMENTS.items():
        text = text.replace(uni, ascii_)
    # Final safety net: drop/replace anything still outside Latin-1
    return text.encode("latin-1", errors="replace").decode("latin-1")

_orig_gen_text = t.gen_text
_orig_gen_typing_text = t.gen_typing_text

def gen_text(text, *args, **kwargs):
    return _orig_gen_text(_sanitize_text(text), *args, **kwargs)

def gen_typing_text(text, *args, **kwargs):
    return _orig_gen_typing_text(_sanitize_text(text), *args, **kwargs)

t.gen_text = gen_text
t.gen_typing_text = gen_typing_text



# --------------------------------------------
# $ whoami
# --------------------------------------------
t.gen_prompt(row_num=1)
t.gen_typing_text("whoami", row_num=1, contin=True, speed=1)
t.clone_frame(5)

whoami_lines = [
    "",
    "Shipped 2X YC-backed, Antler-backed, NSRCEL-IIMB-backed startups, IICPC and",
    "2 prominent companies based in SF",
    "Majoring in CS & Math (core CS, Math, Computing & Statistics)",
    "Part of YC Startup School and GSSoC'26",
    "Building True-Intelligence Systems",
    "Led several software teams, students and clubs and also mentored developers ",
    "Looking to get into AI-Research/ Entrepreneurship!",
    " ",
    "compact{",
    "    builder of strange systems",
    "    collector of hard problems",
    "    turning ideas into machines",
    "    systems thinker · terminal native",
    "    debugging what everyone else gave up",
    "}",
    "",
]

for i, line in enumerate(whoami_lines, start=3):
    t.gen_text(line, row_num=i)
    t.clone_frame(1)

t.clone_frame(40)

# --------------------------------------------
# $ clear
# --------------------------------------------
t.gen_prompt(row_num=(i+2))
t.gen_typing_text("clear", row_num=(i+2), contin=True, speed=1)
t.clone_frame(5)
t.clear_frame()

# --------------------------------------------
# $ interests
# --------------------------------------------
t.gen_prompt(row_num=1)
t.gen_typing_text("interests", row_num=1, contin=True, speed=1)
t.clone_frame(5)

interests_lines = [
    "",
    "LLM, AGI, GenAI, AI: Agents, Solutions, Frameworks, Multi-agents/ Swarms,",
    "Self-optimization, True-intelligence;",
    "High Frequency Algo-Trading & Quantitative Finance; ",
    "Quantum Mechanics, Computing, Cryptography, Key Distribution, Algorithms,", 
    "ML & Communication; ",
    "Particle Physics, Astrophysics & Nuclear Physics; ",
    "Algorithm Development; Backend Development; ",
    "Founder’s Office (GTM); Entrpreneurship.",
]

for i, line in enumerate(interests_lines, start=2):
    t.gen_text(line, row_num=i)
    t.clone_frame(2)

t.clone_frame(40)

# --------------------------------------------
# $ clear
# --------------------------------------------
t.gen_prompt(row_num=12)
t.gen_typing_text("clear", row_num=12, contin=True, speed=1)
t.clone_frame(5)
t.clear_frame()

# --------------------------------------------
# $ philosophy
# --------------------------------------------
t.gen_prompt(row_num=1)
t.gen_typing_text("philosophy", row_num=1, contin=True, speed=1)
t.clone_frame(5)

philosophy_lines = [
    "",
    "Show up. Everyday. No Matter how many times you've failed - or how horrible yesterday was.",
    "Cuz today is still yours!",
    "build > talk",
    "curiosity > credentials",
    "shipping > perfection",
    "experience > assumption",
    "originality > imitation",
    "progress > perfection",
    "meaning > noise",
]

for i, line in enumerate(philosophy_lines, start=2):
    t.gen_text(line, row_num=i)
    t.clone_frame(2)

t.clone_frame(25)

# --------------------------------------------
# $ clear
# --------------------------------------------
t.gen_prompt(row_num=13)
t.gen_typing_text("clear", row_num=13, contin=True, speed=1)
t.clone_frame(5)
t.clear_frame()

# --------------------------------------------
# $ status
# $ archetype
# $ personality
# $ vision
# $ weaknesses
# --------------------------------------------
t.gen_prompt(row_num=1)
t.gen_typing_text("status", row_num=1, contin=True, speed=1)
t.clone_frame(3)

t.gen_text("    > BUILDING [FINAL STAGE]", row_num=2)
t.gen_text("    > SHIPPING", row_num=3)
t.gen_text("    > MARKETING & SALES [STARTED]", row_num=4)
t.clone_frame(10)

t.gen_text("", row_num=5)
t.gen_prompt(row_num=6)
t.gen_typing_text("archetype", row_num=6, contin=True, speed=1)
t.clone_frame(3)
t.gen_text("the systems builder", row_num=7)
t.gen_text("part engineer, part tinkerer, part obsessive explorer", row_num=8)
t.clone_frame(10)

t.gen_text("", row_num=9)
t.gen_prompt(row_num=10)
t.gen_typing_text("personality", row_num=10, contin=True, speed=1)
t.clone_frame(3)

personality_line = "curious · opinionated · detail-obsessed · experimental · iterative · quietly ambitious"
t.gen_text(personality_line, row_num=11)
t.clone_frame(10)

t.gen_text("", row_num=12)
t.gen_prompt(row_num=13)
t.gen_typing_text("vision", row_num=13, contin=True, speed=1)
t.clone_frame(3)
t.gen_text("build true intelligence", row_num=14)
t.clone_frame(10)

t.gen_text("", row_num=15)
t.gen_prompt(row_num=16)
t.gen_typing_text("weaknesses", row_num=16, contin=True, speed=1)
t.clone_frame(3)
t.gen_text("overthinking the details", row_num=17)
t.gen_text("starting one more experiment", row_num=18)
t.gen_text("wanting the system to be just a little cleaner", row_num=18)
t.clone_frame(40)

# --------------------------------------------
# $ clear
# --------------------------------------------
t.gen_text("", row_num=19)
t.gen_prompt(row_num=20)
t.gen_typing_text("clear", row_num=20, contin=True, speed=1)
t.clone_frame(5)
t.clear_frame()

# --------------------------------------------
# Skills image sequence
# --------------------------------------------
# README_TERMINAL.txt specifies these exact three commands.
for row, command in enumerate([
    "import skills.exe from stack",
    "compile skills.exe",
    "load skills.exe",
], start=1):
    t.gen_prompt(row_num=row)
    t.gen_typing_text(command, row_num=row, contin=True, speed=1)
    t.clone_frame(4)

# Exact README marker text.
t.gen_text("", row_num=4)
t.gen_text("(Display image SKILLS.png for 5s)", row_num=5)
t.clone_frame(SKILLS_HOLD_FRAMES)

# Replace the last five seconds of those frames with the actual SKILLS image.
if not Path(SKILLS_PATH).exists():
    raise FileNotFoundError(
        f"Missing {SKILLS_PATH}. Add SKILLS.png to the assets directory."
    )
patch_latest_frames_with_image(
    SKILLS_PATH,
    frame_count=SKILLS_HOLD_FRAMES,
    max_w=720,
    max_h=560,
)

t.gen_text("", row_num=6)
t.gen_text("Ctrl^ X", row_num=7)
t.clone_frame(15)

# --------------------------------------------
# $ clear
# --------------------------------------------
t.gen_prompt(row_num=9)
t.gen_typing_text("clear", row_num=9, contin=True, speed=1)
t.clone_frame(5)
t.clear_frame()

# --------------------------------------------
# $ uptime
# --------------------------------------------
t.gen_prompt(row_num=1)
t.gen_typing_text("uptime", row_num=1, contin=True, speed=1)
t.clone_frame(5)

uptime_lines = [
    "",
    "curiosity       [##########] 100%",
    "energy          [########--]  80%",
    "patience        [######----]  60%",
    "sleep           [###-------]  30%",
    "overthinking    [##########]#####  150%",
    "experimentation [##########]##  120%",
    "coffee          [##########]  100%",
    "unfinished_work [##########]########## 200%",
    "ideas           [##########]#################### 300%",
]
for i, line in enumerate(uptime_lines, start=2):
    t.gen_text(line, row_num=i)
    t.clone_frame(2)
t.clone_frame(20)

# --------------------------------------------
# $ clear
# --------------------------------------------
t.gen_prompt(row_num=13)
t.gen_typing_text("clear", row_num=13, contin=True, speed=1)
t.clone_frame(5)
t.clear_frame()

# --------------------------------------------
# $ system_check
# --------------------------------------------
t.gen_prompt(row_num=1)
t.gen_typing_text("system_check", row_num=1, contin=True, speed=1)
t.clone_frame(5)

system_check_lines = [
    "",
    "CORE",
    "\t[ OK ] curiosity",
    "\t[ OK ] imagination",
    "\t[ OK ] independence",
    "\t[ OK ] ambition",
    "\t[ OK ] adaptability",
    "\t[ OK ] sense of humor",
    "\t[ OK ] willingness to experiment",
    "",
    "BEHAVIOR",
    "\t[PASS] learns quickly",
    "\t[PASS] questions defaults ",
    "\t[PASS] seeks novelty ",
    "\t[WARN] finishes everything",
    "\t[WARN] too many ideas",
    "\t[WARN] \"one more thing\"",
    "",
    "KNOWN ISSUES",
    "  overthinking ........... ACTIVE",
    "  rabbit holes ........... ACTIVE",
    "  perfectionism .......... INTERMITTENT",
    "  sleep .................. DEGRADED",
    "",
    "[FAIL] unable to market and sell product",
    "",
    "SYSTEM",
    "  stable",
    "  evolving",
    "  occasionally chaotic",
    "",
    "SYSTEM: OPERATIONAL",
    "RESULT: HEALTHY ENOUGH TO SHIP",
]

# Split into two viewport-sized chunks (23-row terminal), with a real
# `clear` between them so the second chunk gets a fresh row range.
first_chunk = system_check_lines[:17]   # CORE + BEHAVIOR — 18 lines
second_chunk = system_check_lines[17:]  # KNOWN ISSUES onward — 13 lines

for i, line in enumerate(first_chunk, start=2):
    t.gen_text(line, row_num=i)
    if line:
        t.clone_frame(1)
# rows used: 2..19

t.clone_frame(15)

# --------------------------------------------
# $ clear (between chunks — first_chunk alone reaches row 19,
# adding second_chunk on top would overflow row 23)
# --------------------------------------------
t.gen_prompt(row_num=21)
t.clone_frame(5)
t.clear_frame()

for i, line in enumerate(second_chunk, start=1):
    t.gen_text(line, row_num=i)
    if line:
        t.clone_frame(1)
# rows used: 1..13

t.clone_frame(35)

# --------------------------------------------
# $ clear
# --------------------------------------------
t.gen_prompt(row_num=18)
t.gen_typing_text("clear", row_num=18, contin=True, speed=1)
t.clone_frame(5)
t.clear_frame()

# --------------------------------------------
# $ contrib_stats  (GitHub contribution + lines-of-code stats)
# --------------------------------------------
# Populated by running fetch_github_stats.py first, which requires a
# GitHub Personal Access Token — see that script's docstring for scopes.
# If assets/github_stats.json isn't there, this whole section is skipped
# and the rest of the GIF builds normally.
GITHUB_STATS_PATH = "assets/github_stats.json"

if Path(GITHUB_STATS_PATH).exists():
    import json as _json

    with open(GITHUB_STATS_PATH) as _f:
        _stats = _json.load(_f)

    t.gen_prompt(row_num=1)
    t.gen_typing_text("contrib_stats", row_num=1, contin=True, speed=1)
    t.clone_frame(5)

    _weekday_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    _avg_wd = _stats.get("avg_per_weekday", {})
    _hourly = _stats.get("hourly_commit_counts", {})

    if _hourly:
        _peak_hour = max(_hourly, key=lambda h: _hourly[h])
        _peak_count = _hourly[_peak_hour]
    else:
        _peak_hour, _peak_count = "N/A", 0

    contrib_lines = [
        "",
        f"total contributions ... {_stats.get('total_contributions', 0)}",
        f"avg / day ............. {_stats.get('avg_per_day', 0)}",
        f"avg / week ............ {_stats.get('avg_per_week', 0)}",
        "",
        "avg contributions by weekday:",
    ] + [
        f"  {wd:<4} {_avg_wd.get(wd, 0)}" for wd in _weekday_order
    ] + [
        "",
        f"peak commit hour ...... {_peak_hour}:00 UTC ({_peak_count} commits)",
        "  (hourly stats: last ~90d sample only)",
        "",
        f"lines added ........... {_stats.get('total_additions', 0)}",
        f"lines deleted .......... {_stats.get('total_deletions', 0)}",
        f"net lines .............. {_stats.get('net_lines', 0)}",
    ]

    for i, line in enumerate(contrib_lines, start=2):
        t.gen_text(line, row_num=i)
        t.clone_frame(1)
    t.clone_frame(25)

    # --------------------------------------------
    # $ clear
    # --------------------------------------------
    t.gen_prompt(row_num=(i + 2))
    t.gen_typing_text("clear", row_num=(i + 2), contin=True, speed=1)
    t.clone_frame(5)
    t.clear_frame()
else:
    print(
        f"WARNING: {GITHUB_STATS_PATH} not found — skipping the "
        "contrib_stats section. Run fetch_github_stats.py first "
        "(needs a GitHub PAT; see that script's docstring for scopes)."
    )

# --------------------------------------------
# Final messages + ClipWallet QR
# --------------------------------------------
t.gen_prompt(row_num=1)
t.gen_typing_text('echo "Thanks for visiting"*3', row_num=1, contin=True, speed=1)
t.clone_frame(5)
t.gen_text("Thanks for visiting", row_num=2)
t.gen_text("Thanks for visiting", row_num=3)
t.gen_text("Thanks for visiting", row_num=4)
t.clone_frame(30)

t.gen_prompt(row_num=6)
t.gen_typing_text('echo "Support {ClipWallet}"', row_num=6, contin=True, speed=1)
t.clone_frame(5)
t.gen_text(
    "Support ClipWallet by:",
    row_num=7,
)
t.gen_text("staring the repo; ", row_num=8,)
t.gen_text("fork for open-source development; and", row_num=9,)
t.gen_text("download quick!", row_num=10,)
t.clone_frame(10)

t.gen_text(
    "github.com/shaaravraghu/ClipWallet",
    row_num=12,
)
t.clone_frame(40)


# Hold the final terminal text, then show the real QR code in the same frames.
FINAL_QR_HOLD_FRAMES = 75
try:
    qr_path = create_qr_code(CLIPWALLET_URL, QR_PATH)
    print(f"INFO: QR code created at {qr_path}")
except Exception as e:
    print(f"WARNING: QR code generation failed ({type(e).__name__}: {e})")
    qr_path = None

t.clone_frame(FINAL_QR_HOLD_FRAMES)

if qr_path:
    try:
        patch_latest_frames_with_qr(qr_path, FINAL_QR_HOLD_FRAMES)
        print("INFO: QR code patched into final frames")
    except Exception as e:
        print(f"WARNING: QR patching failed ({type(e).__name__}: {e})")

# ============================================
# Post-process frames → Liquid Glass effect
# ============================================

base_canvas, chrome = prepare_glass_layers(WALLPAPER_PATH)
post_process_frames(base_canvas, chrome)

# ============================================
# Generate GIF
# ============================================

t.gen_gif()

print("\nGIF generated: output.gif")
print("\nREADME_TERMINAL.txt was not modified.")
print("Use: ![Terminal GIF](./output.gif)")
