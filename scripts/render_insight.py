#!/usr/bin/env python3
"""insight-shorts: scene.json 대로 9:16 렌더 + 중앙 박스 자막 하드번인.

샷마다 크롭 배율이 다르므로(fill/zoom/fit) 하나의 crop 필터로는 표현할 수 없다.
그래서 샷을 프레임 단위로 잘라 각각 1080x1920 으로 렌더한 뒤 concat 으로 붙이고,
자막은 이어붙인 무음 비디오에 한 번만 태운다. 오디오는 마스터에서 그대로 가져온다.

  fill / zoom : crop(rect) -> scale 1080x1920 -> 켄번즈 슬로우 줌
  fit         : 배경 = 전체 프레임 확대 + 블러, 전경 = 16:9 원본을 상단 밴드에 얹음
"""
import argparse
import json
import os
import subprocess
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))

def _resolve(env_var, name, fallback):
    val = os.environ.get(env_var)
    if val and os.path.exists(val):
        return val
    which = shutil.which(name)
    if which:
        return which
    if os.path.exists(fallback):
        return fallback
    return fallback

FFMPEG = _resolve("FFMPEG_PATH", "ffmpeg", "/opt/homebrew/bin/ffmpeg")
FFPROBE = _resolve("FFPROBE_PATH", "ffprobe", "/opt/homebrew/bin/ffprobe")
FONTS_DIR = os.environ.get("FONTS_DIR") or os.path.expanduser("~/Library/Fonts")
OUT_W, OUT_H = 1080, 1920


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def run(cmd, **kw):
    subprocess.run(cmd, check=True, **kw)


def shot_frames(shots, fps, duration):
    """샷 경계를 프레임 격자에 스냅해 빈틈·겹침 없이 만든다."""
    total = int(round(duration * fps))
    bounds = [0]
    for sh in shots[:-1]:
        n = min(max(int(round(sh["t1"] * fps)), bounds[-1] + 1), total - 1)
        bounds.append(n)
    bounds.append(total)
    return [(bounds[i], bounds[i + 1]) for i in range(len(shots))]


def build_vf(sh, src_w, src_h, band_y, band_h, blur, nf=1, max_up=2.8,
             bg="blur", align="center", border="0x0E1626"):
    """샷 하나의 필터 체인. 반환: (filter_complex, 출력라벨)

    band : rect 를 밴드(1080 x band_h) 안에 통째로 얹는다. 자료가 잘리지 않는다.
    fill : rect(9:16)로 화면을 꽉 채운다. 인물 토킹헤드·영상 클립용.

    bg    : blur(기존 죽인 블러) | black(순검정 — 오너 지시 2026-09-07)
    align : center(밴드 세로 중앙) | bottom(밴드 하단에 붙임 — 자료 하단 위에
            자막을 얹는 레이아웃에서 자료 아랫변 위치를 샷마다 고정한다)
    """
    mode = sh["mode"]
    kb = float(sh.get("kb") or 0.0)
    x, y, w, h = [int(round(v)) for v in sh["rect"]]

    if mode == "fill":
        chain = (f"[0:v]crop={w}:{h}:{x}:{y},"
                 f"scale={OUT_W}:{OUT_H}:flags=lanczos")
        if kb > 0 and nf > 1:
            # ★zoompan 에는 총 프레임수 상수 N 이 없다(2026-09-06 실측:
            #   "Undefined constant"). 샷 길이를 파이썬에서 아니 상수로 박는다.
            chain += (f",zoompan=z='min(1+{kb:.4f}*on/{nf-1},{1+kb:.4f})':"
                      f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                      f"d=1:s={OUT_W}x{OUT_H}")
        return chain + "[vout]", "[vout]"

    # band — 스케일 배율은 밴드에 맞추되 화질 보호를 위해 상한을 둔다
    scale = min(OUT_W / w, band_h / h, max_up)
    bw = int(round(w * scale / 2) * 2)
    bh = int(round(h * scale / 2) * 2)
    ox = (OUT_W - bw) // 2
    if align == "bottom":
        oy = band_y + band_h - bh
    else:
        oy = band_y + (band_h - bh) // 2
    if bg == "black":
        # 순검정 배경 — 자료만 남긴다(오너 지시 2026-09-07). 프레임 수를 유지해야
        # 하므로 color 소스를 새로 만들지 않고 원본을 통째로 덮어 칠한다.
        bg_chain = (f"[bg]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
                    f"crop={OUT_W}:{OUT_H},"
                    f"drawbox=x=0:y=0:w={OUT_W}:h={OUT_H}:color=black@1:t=fill[bgo];")
    else:
        # 배경은 '있는지 없는지 모를 정도로' 죽인다. 원본 제목이 읽히면 밴드 안
        # 자료와 경쟁해서 지저분해진다(2026-09-06 스모크 실측).
        bg_chain = (f"[bg]scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
                    f"crop={OUT_W}:{OUT_H},gblur=sigma={blur},"
                    f"eq=brightness=-0.28:saturation=0.55[bgo];")
    chain = (
        f"[0:v]split=2[bg][fg];"
        + bg_chain +
        f"[fg]crop={w}:{h}:{x}:{y},scale={bw}:{bh}:flags=lanczos,"
        f"pad={bw+6}:{bh+6}:3:3:color={border}[fgo];"
        f"[bgo][fgo]overlay=x={ox-3}:y={oy-3}[vout]"
    )
    return chain, "[vout]"


def main():
    ap = argparse.ArgumentParser(description="scene.json 기반 9:16 렌더")
    ap.add_argument("--in", dest="in_path", required=True)
    ap.add_argument("--scene", required=True)
    ap.add_argument("--ass", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--band-y", type=int, default=190,
                    help="band 모드 밴드 영역의 상단 Y")
    ap.add_argument("--band-h", type=int, default=880,
                    help="band 영역 높이. band_y+band_h 가 자막 위여야 한다")
    ap.add_argument("--max-up", type=float, default=2.8,
                    help="band 스케일 상한(원본 화질 보호)")
    ap.add_argument("--blur", type=float, default=44.0)
    ap.add_argument("--bg", choices=["blur", "black"], default="blur",
                    help="밴드 뒤 배경. black = 순검정(오너 지시 2026-09-07)")
    ap.add_argument("--band-align", choices=["center", "bottom"], default="center",
                    help="밴드 안 자료의 세로 정렬. bottom 이면 자료 아랫변이 "
                         "밴드 하단에 고정돼 자막 위치가 샷마다 흔들리지 않는다")
    ap.add_argument("--band-border", default="0x0E1626", help="밴드 테두리 색")
    ap.add_argument("--bitrate", default="16M")
    ap.add_argument("--no-subs", action="store_true")
    args = ap.parse_args()

    with open(args.scene, "r", encoding="utf-8") as f:
        scene = json.load(f)
    src_w, src_h = scene["src_w"], scene["src_h"]
    fps, duration = scene["fps"], scene["duration"]
    shots = scene["shots"]

    workdir = args.workdir or os.path.join(os.path.dirname(
        os.path.abspath(args.out)), "_work")
    os.makedirs(workdir, exist_ok=True)
    stem = os.path.splitext(os.path.basename(args.out))[0]
    parts_dir = os.path.join(workdir, f"{stem}_parts")
    os.makedirs(parts_dir, exist_ok=True)
    for old in os.listdir(parts_dir):                     # 묵은 조각 제거
        os.remove(os.path.join(parts_dir, old))

    in_abs = os.path.abspath(args.in_path)
    frames = shot_frames(shots, fps, duration)
    part_paths = []
    for i, (sh, (n0, n1)) in enumerate(zip(shots, frames)):
        nf = n1 - n0
        if nf <= 0:
            continue
        chain, vlabel = build_vf(sh, src_w, src_h, args.band_y,
                                 args.band_h, args.blur, nf, args.max_up,
                                 args.bg, args.band_align, args.band_border)
        part = os.path.join(parts_dir, f"{i:04d}.mp4")
        cmd = [FFMPEG, "-y", "-v", "error", "-ss", f"{n0/fps:.6f}", "-i", in_abs,
               "-frames:v", str(nf), "-an",
               "-filter_complex", chain, "-map", vlabel,
               "-c:v", "h264_videotoolbox", "-b:v", "24M", "-maxrate", "30M",
               "-pix_fmt", "yuv420p", "-r", f"{fps:.6f}", part]
        run(cmd)
        part_paths.append(part)
        log(f"[render] {i+1}/{len(shots)} {sh['mode']:4s} "
            f"{n0/fps:6.2f}s +{nf:4d}f rect={sh['rect']}")

    concat_txt = os.path.join(parts_dir, "concat.txt")
    with open(concat_txt, "w", encoding="utf-8") as f:
        for p in part_paths:
            f.write(f"file '{os.path.basename(p)}'\n")
    silent = os.path.join(workdir, f"{stem}_silent.mp4")
    run([FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0",
         "-i", concat_txt, "-c", "copy", silent], cwd=parts_dir)

    out_abs = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_abs), exist_ok=True)
    cmd = [FFMPEG, "-y", "-v", "error", "-i", silent, "-i", in_abs]
    if args.no_subs or not args.ass:
        cmd += ["-map", "0:v", "-map", "1:a", "-c:v", "copy"]
    else:
        ass_abs = os.path.abspath(args.ass)
        cmd += ["-filter_complex",
                f"[0:v]ass='{os.path.basename(ass_abs)}':"
                f"fontsdir='{FONTS_DIR}'[v]",
                "-map", "[v]", "-map", "1:a",
                "-c:v", "h264_videotoolbox", "-b:v", args.bitrate,
                "-maxrate", "20M", "-pix_fmt", "yuv420p"]
    cmd += ["-r", f"{fps:.6f}", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-shortest", "-movflags", "+faststart", out_abs]
    cwd = os.path.dirname(os.path.abspath(args.ass)) if (args.ass and not args.no_subs) else None
    run(cmd, cwd=cwd)

    info = json.loads(subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,nb_frames",
         "-show_entries", "format=duration", "-of", "json", out_abs],
        check=True, stdout=subprocess.PIPE, text=True).stdout)
    st, fm = info["streams"][0], info["format"]
    got = float(fm["duration"])
    log(f"[완료] {out_abs} {st['width']}x{st['height']} {got:.3f}s "
        f"(마스터 {duration:.3f}s, 차 {got-duration:+.3f}s) 샷 {len(part_paths)}개")
    if abs(got - duration) > 0.15:
        log(f"⚠ 길이 오차 {got-duration:+.3f}s — 샷 경계 스냅을 확인하라")


if __name__ == "__main__":
    main()
