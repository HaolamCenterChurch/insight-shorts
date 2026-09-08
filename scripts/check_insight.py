#!/usr/bin/env python3
"""insight-shorts 완성본 하드 게이트.

설교 쇼츠의 check_output.py 를 그대로 쓸 수 없다 — 저기 G-D(카메라 모션)는
'인물을 따라 계속 움직여야 한다'가 기준이지만, 해설 쇼츠는 자료를 보여주는
고정 샷이 정상이기 때문이다. 자막 게이트(G-A/B/C)는 검증된 로직을 그대로 쓰고,
카메라 대신 **레이아웃(G-L)** 과 **자막 스타일(G-S)** 을 잰다.

종료 코드 0=통과, 1=실패.
"""
import argparse
import json
import os
import re
import subprocess
import sys

import numpy as np

import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from check_output import (Report, first_speech, parse_ass, voiced_track,  # noqa: E402
                          wait_after, TH_BLOCK_WAIT_MAX, TH_BLOCK_WAIT_RATIO,
                          TH_HEAD_LEAD, TH_MIN_DUR, TH_SHORT_RATIO,
                          TH_SIMILARITY)

FFMPEG = os.environ.get("FFMPEG_PATH") or shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
FFPROBE = os.environ.get("FFPROBE_PATH") or shutil.which("ffprobe") or "/opt/homebrew/bin/ffprobe"

TH_MAX_UPSCALE = 2.8      # G-L 출력 업스케일 상한 1080/크롭폭 (원본 화질 보호)
TH_MIN_SHOT = 1.00        # G-L 평균 샷 길이 하한(초)
TH_MIN_FS = 88            # G-S 한글 자막 최소 크기(pt)
TH_LEN_TOL = 0.20         # G-F 마스터 대비 길이 허용 오차(초)
INTRO_MAX = 1.60          # 썸네일 인트로가 붙었을 때의 최대 증가분(초)


def dur_of(path):
    out = subprocess.run([FFPROBE, "-v", "error", "-show_entries",
                          "format=duration", "-of", "csv=p=0", path],
                         check=True, stdout=subprocess.PIPE, text=True).stdout
    return float(out.strip())


def main():
    ap = argparse.ArgumentParser(description="insight-shorts 게이트")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--band-y", type=int, default=190)
    ap.add_argument("--band-h", type=int, default=880)
    ap.add_argument("--max-up", type=float, default=2.8)
    ap.add_argument("--layout", choices=["band-below", "overlay"],
                    default="band-below",
                    help="band-below: 자막이 밴드 아래(정본) / "
                         "overlay: 자막이 자료 안 하단(오너 지시 2026-09-07)")
    ap.add_argument("--skip-naming", action="store_true")
    args = ap.parse_args()

    outdir = os.path.abspath(args.outdir)
    work = os.path.join(outdir, "_work")
    slug = args.slug
    ass = os.path.join(work, f"{slug}.ass")
    scene_path = os.path.join(work, f"{slug}_scene.json")
    master = os.path.join(work, f"{slug}_master.mov")
    mp4 = os.path.join(outdir, f"{slug}.mp4")
    verify = os.path.join(outdir, f"{slug}_verify.md")
    rep = Report()

    # ── 자막 타이밍 G-A / G-B / G-C ────────────────────────────────
    blocks = parse_ass(ass)
    wav = os.path.join(work, f"{slug}_gate.wav")
    subprocess.run([FFMPEG, "-y", "-v", "error", "-i", master, "-vn",
                    "-ac", "1", "-ar", "16000", wav], check=True)
    voiced = voiced_track(wav)
    speech0 = first_speech(voiced)
    lead = speech0 - blocks[0][0]
    rep.add("G-A", "첫 자막 리드", f"{lead:+.2f}s",
            f"≤{TH_HEAD_LEAD:.2f}s", lead <= TH_HEAD_LEAD)

    waits = np.array([wait_after(voiced, s) for s, _, _ in blocks])
    over = float((waits > 0.5).mean())
    rep.add("G-B", "블록 대기 최대", f"{waits.max():.2f}s",
            f"≤{TH_BLOCK_WAIT_MAX:.2f}s", waits.max() <= TH_BLOCK_WAIT_MAX)
    rep.add("G-B", "0.5초 초과 비율", f"{100*over:.0f}%",
            f"≤{100*TH_BLOCK_WAIT_RATIO:.0f}%", over <= TH_BLOCK_WAIT_RATIO)

    durs = np.array([e - s for s, e, _ in blocks])
    short = float((durs < 1.0).mean())
    rep.add("G-C", "블록 최단 표시", f"{durs.min():.2f}s",
            f"≥{TH_MIN_DUR:.2f}s", durs.min() >= TH_MIN_DUR)
    rep.add("G-C", "1초 미만 비율", f"{100*short:.0f}%",
            f"≤{100*TH_SHORT_RATIO:.0f}%", short <= TH_SHORT_RATIO)

    # ── 레이아웃 G-L ───────────────────────────────────────────────
    with open(scene_path, encoding="utf-8") as f:
        scene = json.load(f)
    shots = scene["shots"]
    sw, sh_h = scene["src_w"], scene["src_h"]
    modes = {}
    for s in shots:
        modes[s["mode"]] = modes.get(s["mode"], 0) + 1
    avg_shot = scene["duration"] / max(len(shots), 1)
    rep.add("G-L", "샷 구성", f"{len(shots)}개 {modes}",
            f"평균 ≥{TH_MIN_SHOT:.2f}s", avg_shot >= TH_MIN_SHOT)

    ups = []
    for s in shots:
        rw, rh = s["rect"][2], s["rect"][3]
        ups.append(1080.0 / rw if s["mode"] == "fill"
                   else min(1080.0 / rw, args.band_h / rh, args.max_up))
    max_up = max(ups) if ups else 1.0
    rep.add("G-L", "최대 업스케일", f"{max_up:.2f}배",
            f"≤{TH_MAX_UPSCALE:.1f}배", max_up <= TH_MAX_UPSCALE + 1e-6)

    bad = [s for s in shots
           if s["rect"][0] < 0 or s["rect"][1] < 0
           or s["rect"][0] + s["rect"][2] > sw + 1
           or s["rect"][1] + s["rect"][3] > sh_h + 1
           or (s["mode"] == "fill"
               and abs(s["rect"][2] / s["rect"][3] - 9 / 16) > 0.02)]
    rep.add("G-L", "크롭 박스 유효", f"이상 {len(bad)}개",
            "프레임 안 · fill 은 9:16", not bad)
    # ── 자막 스타일 G-S (오너 지시 준수) ───────────────────────────
    style = ""
    for line in open(ass, encoding="utf-8"):
        if line.startswith("Style:"):
            style = line.strip()
            break
    f = style.split(",")
    fs = int(float(f[2])) if len(f) > 3 else 0
    # Format 순서: 0 Name,1 Fontname,2 Fontsize,3 Primary,4 Secondary,5 Outline,
    # 6 Back,7 Bold,8 Italic,9 Underline,10 StrikeOut,11 ScaleX,12 ScaleY,
    # 13 Spacing,14 Angle,15 BorderStyle,16 Outline,17 Shadow,18 Alignment
    border, outline, shadow, align = (f[15], f[16], f[17], f[18]) if len(f) > 18 \
        else ("?", "?", "?", "?")
    rep.add("G-S", "글자 크기", f"{fs}pt", f"≥{TH_MIN_FS}pt", fs >= TH_MIN_FS)
    rep.add("G-S", "박스/그림자", f"BorderStyle={border} Shadow={shadow}",
            "박스 3 · 그림자 0", border == "3" and float(shadow) == 0.0)
    body = open(ass, encoding="utf-8").read()
    want_an = 2 if args.layout == "overlay" else 5
    dialogs = re.findall(r"Dialogue: 0,[^\n]*Box,[^\n]*", body)
    an_ok = all(f"\\an{want_an}" in t for t in dialogs)
    rep.add("G-S", "가로 가운데 배치",
            f"Alignment={align} an{want_an}={an_ok}",
            f"an{want_an}", align == "5" and an_ok)

    pos_ys = [int(m) for m in
              re.findall(r"Box,,0,0,0,,\{\\an\d\\pos\(540,(\d+)\)", body)]
    pos_y = pos_ys[0] if pos_ys else 960
    two_line_h = fs * 1.25 * 2 + 2 * 14           # 두 줄 자막 높이 추정
    band_bottom = args.band_y + args.band_h
    if args.layout == "overlay":
        # 자막은 자료 아랫변에 '걸친다' — 윗부분만 자료를 물고 아래로 빠져나온다.
        # 다 덮어버리면(겹침이 자료 높이의 45% 초과) 자료가 안 보이고,
        # 아예 안 물면 자료와 떨어진 자막이 되어 오너가 지시한 배치가 아니다.
        n_lines = 2 if any("\\N" in t for t in dialogs) else 1
        sub_h = fs * 1.25 * n_lines + 2 * 14
        sub_top = pos_y - sub_h
        # 자막은 자료 위에 얹힌다 — 자료 안에 다 들어가거나(자료가 클 때)
        # 아랫변에 걸친다(자료가 작을 때). 절반 이상 물지 못하면 배치 실패.
        inter = max(0.0, min(pos_y, band_bottom) - max(sub_top, args.band_y))
        ratio = inter / sub_h
        ok_band = ("band" not in modes) or (ratio >= 0.5 and sub_top >= args.band_y)
        rep.add("G-L", "자막-자료 겹침",
                f"{n_lines}줄 자막 {sub_top:.0f}~{pos_y}px / 자료 {args.band_y}~"
                f"{band_bottom}px (물린 비율 {ratio*100:.0f}%)",
                "자막이 자료 위(≥50%)", ok_band)
    else:
        sub_top = pos_y - two_line_h / 2           # an5 기준 상단 추정
        ok_band = ("band" not in modes) or (band_bottom <= sub_top)
        rep.add("G-L", "밴드-자막 간섭",
                f"밴드 하단 {band_bottom}px / 자막 상단 {sub_top:.0f}px",
                "밴드가 자막 위", ok_band)

    # ── 렌더 일치 G-F ──────────────────────────────────────────────
    m_dur, v_dur = dur_of(master), dur_of(mp4)
    delta = v_dur - m_dur
    ok_len = -TH_LEN_TOL <= delta <= INTRO_MAX
    rep.add("G-F", "완성본 길이", f"{v_dur:.2f}s (마스터 {m_dur:.2f}s, {delta:+.2f}s)",
            f"-{TH_LEN_TOL}s ~ +{INTRO_MAX}s", ok_len)
    ass_end = max(e for _, e, _ in blocks)
    rep.add("G-F", "ASS 종료 vs 마스터", f"{ass_end:.2f}s",
            f"±{TH_LEN_TOL}s", abs(ass_end - m_dur) <= TH_LEN_TOL)

    # ── 산출 규칙 G-E ──────────────────────────────────────────────
    if not args.skip_naming:
        sim = None
        if os.path.exists(verify):
            m = re.search(r"([0-9.]+)\s*%", open(verify, encoding="utf-8").read())
            sim = float(m.group(1)) if m else None
        rep.add("G-E", "재전사 유사도",
                f"{sim:.1f}%" if sim is not None else "리포트 없음",
                f"≥{TH_SIMILARITY}%", sim is not None and sim >= TH_SIMILARITY)
        thumbs = [t for t in ("_thumb_youtube.jpg", "_thumb_instagram.jpg",
                              "_thumb_instagram_guide.jpg")
                  if os.path.exists(os.path.join(outdir, slug + t))]
        rep.add("G-E", "썸네일", f"{len(thumbs)}/3종", "3종", len(thumbs) == 3)
        rep.add("G-E", "슬러그", slug, "{ID}_{한글제목}",
                bool(re.match(r"^[A-Z]_[^\s]+$", slug)))

    rep.render(f"insight-shorts 게이트 — {slug}")
    print("\n판정:", "❌ 실패" if rep.failed else "✅ 통과")
    return 1 if rep.failed else 0


if __name__ == "__main__":
    sys.exit(main())
