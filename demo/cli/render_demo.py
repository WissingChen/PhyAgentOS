#!/usr/bin/env python3
"""Render the scripted `paos agent` CLI conversation to an MP4.

Usage:
    python demo/cli/render_demo.py [-o demo/cli/paos_cli_demo.mp4] [--fps 30]

All demo code lives under demo/; the production package is untouched.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from timeline import build_schedule

# ---------------------------------------------------------------- layout ---
W, H, FPS = 1280, 800, 30
TITLE_H = 46
PAD_X, PAD_Y = 34, 28
FONT_SIZE, LH = 23, 34

# ---------------------------------------------------------------- colors ---
PAGE = (7, 9, 12)
BG = (13, 17, 23)
TITLE_BG = (22, 27, 34)
FG = (230, 237, 243)
DIM = (139, 148, 158)
BLUE = (120, 170, 255)
CYAN = (76, 209, 209)
GREEN = (63, 185, 80)
CODE_BG = (42, 46, 54)
STYLES = {"fg": FG, "dim": DIM, "bold": FG, "blue": BLUE, "cyan": CYAN,
          "green": GREEN, "code": FG, "cmd": FG}

NOTO = "/usr/share/fonts/opentype/noto"
FONT_REG = ImageFont.truetype(f"{NOTO}/NotoSansCJK-Regular.ttc", FONT_SIZE, index=7)
FONT_BOLD = ImageFont.truetype(f"{NOTO}/NotoSansCJK-Bold.ttc", FONT_SIZE, index=7)
FONT_SPIN = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", FONT_SIZE)
FONT_FALLBACK = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", FONT_SIZE)
FONT_TITLE = ImageFont.truetype(f"{NOTO}/NotoSansCJK-Regular.ttc", 17, index=2)
FONT_EMOJI = ImageFont.truetype("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf", 109)

EMOJI_CHARS = {"🍞", "✅"}
FALLBACK_CHARS = {"↳"}
_emoji_cache: dict[str, Image.Image] = {}


def emoji_tile(ch: str) -> Image.Image:
    if ch not in _emoji_cache:
        canvas = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
        ImageDraw.Draw(canvas).text((0, 0), ch, font=FONT_EMOJI, embedded_color=True)
        box = canvas.getbbox()
        tile = canvas.crop(box)
        scale = 26 / tile.height
        _emoji_cache[ch] = tile.resize((max(1, round(tile.width * scale)), 26))
    return _emoji_cache[ch]


# ------------------------------------------------------------- terminal ----
def draw_spans(draw: ImageDraw.ImageDraw, img: Image.Image,
               x: float, y: int, spans: list[tuple]) -> float:
    """Draw one line of (text, style) spans; return pen x after the line."""
    for text, style in spans:
        color = STYLES.get(style, FG)
        font = FONT_BOLD if style == "bold" else FONT_REG
        i = 0
        while i < len(text):
            ch = text[i]
            if ch in EMOJI_CHARS:
                img.paste(emoji_tile(ch), (round(x), y + 5), emoji_tile(ch))
                x += emoji_tile(ch).width + 2
                i += 1
                continue
            if ch in FALLBACK_CHARS:
                draw.text((x, y), ch, font=FONT_FALLBACK, fill=color)
                x += FONT_FALLBACK.getlength(ch)
                i += 1
                continue
            run = ch
            for nxt in text[i + 1:]:
                if nxt in EMOJI_CHARS:
                    break
                run += nxt
            if style == "code":
                w = font.getlength(run)
                draw.rectangle([x, y + 3, x + w + 8, y + 27], fill=CODE_BG, width=0)
                draw.text((x + 4, y), run, font=font, fill=color)
                x += w + 8
            else:
                draw.text((x, y), run, font=font, fill=color)
                x += font.getlength(run)
            i += len(run)
    return x


def build_frame(t: float, events: list[tuple],
                 title: str = "paos agent — python -m PhyAgentOS agent") -> Image.Image:
    # ---- replay events ------------------------------------------------------
    lines: list[list] = []
    input_prefix, input_text = None, ""
    spin_start = None
    last_keystroke = -1.0
    for te, kind, payload in events:
        if te > t:
            break
        if kind == "print":
            lines.extend([list(ln) for ln in payload])
        elif kind == "input_start":
            input_prefix, input_text = payload, ""
        elif kind == "input_char":
            input_text += payload
            last_keystroke = te
        elif kind == "input_submit":
            if input_prefix is not None:
                lines.append(list(input_prefix) + [(input_text, "fg")])
            input_prefix, input_text = None, ""
        elif kind == "hint":
            lines.append(list(payload))
        elif kind == "spinner_on":
            spin_start = te
        elif kind == "spinner_off":
            spin_start = None

    # ---- window -------------------------------------------------------------
    img = Image.new("RGB", (W, H), PAGE)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([16, 16, W - 16, H - 16], radius=14, fill=BG)
    draw.rectangle([17, 17, W - 17, 17 + TITLE_H], fill=TITLE_BG)
    for cx, col in ((44, (255, 95, 87)), (70, (254, 188, 46)), (96, (40, 200, 64))):
        draw.ellipse([cx - 7, 17 + TITLE_H // 2 - 7, cx + 7, 17 + TITLE_H // 2 + 7], fill=col)
    title = title
    tw = FONT_TITLE.getlength(title)
    draw.text(((W - tw) / 2, 24), title, font=FONT_TITLE, fill=(120, 129, 140))

    # ---- text ---------------------------------------------------------------
    y = 17 + TITLE_H + PAD_Y
    for line in lines:
        draw_spans(draw, img, PAD_X, y, line)
        y += LH

    if spin_start is not None:  # spinner stays as the bottom status line
        frame = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[int((t - spin_start) / 0.08) % 10]
        draw.text((PAD_X, y), frame, font=FONT_SPIN, fill=DIM)
        draw.text((PAD_X + 26, y), "PhyAgentOS is thinking...", font=FONT_REG, fill=DIM)
        y += LH

    cur_x = None
    if input_prefix is not None:
        cur_x = draw_spans(draw, img, PAD_X, y,
                           list(input_prefix) + [(input_text, "fg")])
        y += LH

    # ---- cursor -------------------------------------------------------------
    if cur_x is not None:
        typing = t - last_keystroke < 0.18
        if typing or (t * 2.0) % 1.0 < 0.55:
            draw.rectangle([cur_x + 2, y - LH + 5, cur_x + 14, y - LH + 29], fill=FG)
    return img


def main() -> None:
    parser = argparse.ArgumentParser(description="paos agent CLI demo → MP4")
    parser.add_argument("-o", "--out", default=str(Path(__file__).parent / "paos_cli_demo.mp4"))
    parser.add_argument("--fps", type=int, default=FPS)
    args = parser.parse_args()

    events, total = build_schedule()
    frames = int(total * args.fps)
    writer = imageio_ffmpeg.write_frames(
        args.out, (W, H), fps=args.fps, codec="libx264",
        pix_fmt_out="yuv420p", quality=8, macro_block_size=1,
    )
    writer.send(None)  # seed the generator
    for i in range(frames):
        writer.send(np.asarray(build_frame(i / args.fps, events)).tobytes())
        if i % 100 == 0:
            print(f"frame {i}/{frames}")
    writer.close()
    print(f"wrote {args.out} ({frames} frames, {total:.1f}s)")


if __name__ == "__main__":
    main()
