#!/usr/bin/env python3
"""渲染分选任务会话（paos agent CLI 流程模拟）到终端画面 MP4。

Usage:
    python demo/cli/paos_sorting_demo.py [-o 输出路径] [--fps 30]
"""

from __future__ import annotations

import argparse
from pathlib import Path

import imageio_ffmpeg
import numpy as np

from render_demo import W, H, build_frame
import sorting_session


def main() -> None:
    parser = argparse.ArgumentParser(description="paos agent 分选任务会话 → MP4")
    parser.add_argument("-o", "--out",
                        default=str(Path(__file__).parent / "paos_sorting_demo.mp4"))
    parser.add_argument("--config", default=str(sorting_session.DEFAULT_CONFIG),
                        help="会话 JSON 路径")
    parser.add_argument("--fps", type=int, default=30)
    args = parser.parse_args()

    config = sorting_session.load_config(args.config)
    events, total = sorting_session.build_schedule(config)
    frames = int(total * args.fps)

    writer = imageio_ffmpeg.write_frames(
        args.out, (W, H), fps=args.fps, codec="libx264",
        pix_fmt_out="yuv420p", quality=8, macro_block_size=1,
    )
    writer.send(None)
    for i in range(frames):
        writer.send(np.asarray(build_frame(i / args.fps, events)).tobytes())
    writer.close()
    print(f"wrote {args.out} ({frames} frames, {total:.1f}s)")


if __name__ == "__main__":
    main()
