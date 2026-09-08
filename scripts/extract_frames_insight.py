#!/usr/bin/env python3
"""썸네일용 클린 9:16 프레임 추출 — scene.json 의 그 시각 레이아웃 그대로.

자막이 번인된 완성본에서 프레임을 뽑으면 썸네일에 본문 자막이 찍힌다.
반드시 클린 마스터(_master.mov)에서 뽑는다.
"""
import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_insight import build_vf  # noqa: E402

FFMPEG = "/opt/homebrew/bin/ffmpeg"


def main():
    ap = argparse.ArgumentParser(description="클린 9:16 썸네일 프레임 추출")
    ap.add_argument("--master", required=True)
    ap.add_argument("--scene", required=True)
    ap.add_argument("--times", nargs="+", type=float, required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--prefix", required=True)
    ap.add_argument("--band-y", type=int, default=190)
    ap.add_argument("--band-h", type=int, default=880)
    ap.add_argument("--bg", choices=["blur", "black"], default="blur",
                    help="본편과 같은 배경으로 뽑는다. overlay 레이아웃이면 black")
    args = ap.parse_args()

    with open(args.scene, encoding="utf-8") as f:
        scene = json.load(f)
    shots = scene["shots"]
    os.makedirs(args.outdir, exist_ok=True)

    for t in args.times:
        sh = next((s for s in shots if s["t0"] <= t < s["t1"]), shots[-1])
        # 정지 프레임엔 켄번즈가 필요 없다(zoompan 은 프레임 스트림 전제)
        chain, vlabel = build_vf(dict(sh, kb=0.0), scene["src_w"],
                                 scene["src_h"], args.band_y, args.band_h, 26.0,
                                 1, 2.8, args.bg)
        out = os.path.join(args.outdir, f"{args.prefix}_{t:06.2f}.jpg")
        subprocess.run([FFMPEG, "-y", "-v", "error", "-ss", f"{t:.3f}",
                        "-i", args.master, "-frames:v", "1",
                        "-filter_complex", chain, "-map", vlabel,
                        "-q:v", "2", out], check=True)
        print(f"{sh['mode']:4s} {t:7.2f}s -> {out}")


if __name__ == "__main__":
    main()
