#!/usr/bin/env python3
"""insight-shorts: 자료화면 해설 영상의 장면별 9:16 레이아웃 결정기.

설교 쇼츠(track_crop.py)는 인물 한 명을 따라가는 등속 패닝이 정답이지만,
해설 영상은 화면이 [진행자 토킹헤드] <-> [지도·차트·자막카드] 로 계속 바뀐다.
그래서 샷마다 무엇이 찍혔는지 보고 셋 중 하나를 고른다.

  band  자료(슬라이드·지도·차트) -> 그 영역만 오려 상단 밴드에 통째로 얹는다.
        rect 를 좁게 잡을수록 확대된다. 자료가 잘리지 않고 자막과도 안 겹친다.
  fill  인물 토킹헤드/영상 클립  -> 얼굴 중심 9:16 크롭으로 화면을 꽉 채운다.

자동 판정은 '기본값'일 뿐이다. 말하는 내용과 화면을 맞추는 것은 사람(에이전트)의
몫이라 plan.json 의 "focus" 로 구간별 수동 지정이 항상 자동 판정을 이긴다.
"""
import argparse
import json
import os
import re
import subprocess
import sys

import cv2
import numpy as np

FFMPEG = "/opt/homebrew/bin/ffmpeg"
FFPROBE = "/opt/homebrew/bin/ffprobe"
OUT_W, OUT_H = 1080, 1920
AR = 9.0 / 16.0          # 크롭 가로세로비
DET_W = DET_H = 384      # YuNet 입력


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def probe(path):
    cmd = [FFPROBE, "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width,height,r_frame_rate",
           "-show_entries", "format=duration", "-of", "json", path]
    info = json.loads(subprocess.run(cmd, check=True, stdout=subprocess.PIPE,
                                     text=True).stdout)
    st = info["streams"][0]
    num, den = st["r_frame_rate"].split("/")
    return (int(st["width"]), int(st["height"]),
            float(num) / float(den), float(info["format"]["duration"]))


def detect_scene_cuts(path, thresh):
    """ffmpeg scene score 로 시각적 컷 지점(초)을 뽑는다."""
    cmd = [FFMPEG, "-v", "info", "-i", path, "-filter:v",
           f"select='gt(scene,{thresh})',showinfo", "-f", "null", "-"]
    proc = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                          stderr=subprocess.PIPE, text=True)
    times = []
    for line in proc.stderr.splitlines():
        if "Parsed_showinfo" not in line:
            continue
        m = re.search(r"pts_time:([0-9.]+)", line)
        if m:
            times.append(float(m.group(1)))
    return sorted(times)


def silence_cut_times(master_path):
    """silence_cut.py 가 지운 자리(편집 타임라인 기준 시각)를 컷으로 본다."""
    cuts_path = master_path + ".cuts.json"
    if not os.path.exists(cuts_path):
        return []
    with open(cuts_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    times, acc = [], 0.0
    for s, e in data.get("keeps", [])[:-1]:
        acc += (e - s)
        times.append(acc)
    return times


def build_shots(cut_times, duration, min_shot):
    """컷 시각 목록을 [t0, t1] 구간으로 만든다. 너무 짧은 샷은 앞에 흡수."""
    bounds = [0.0] + [t for t in sorted(set(round(t, 3) for t in cut_times))
                      if 0.0 < t < duration] + [duration]
    shots = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        if shots and (b - a) < min_shot:
            shots[-1][1] = b
        else:
            shots.append([a, b])
    # 마지막 샷이 짧으면 앞으로 합친다
    if len(shots) >= 2 and (shots[-1][1] - shots[-1][0]) < min_shot:
        shots[-2][1] = shots[-1][1]
        shots.pop()
    return shots


def grab(cap, fps, t):
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(round(t * fps))))
    ok, frame = cap.read()
    return frame if ok else None


def detect_face(detector, frame, w, h):
    """가장 신뢰도 높은 얼굴 -> (cx, cy, fw) 원본 좌표. 없으면 None."""
    small = cv2.resize(frame, (DET_W, DET_H))
    _, faces = detector.detect(small)
    if faces is None or len(faces) == 0:
        return None
    good = [f for f in faces if f[14] >= 0.6 and (f[3] / max(f[2], 1)) >= 0.85]
    if not good:
        return None
    f = max(good, key=lambda f: f[2] * f[3])
    sx, sy = w / DET_W, h / DET_H
    return (float((f[0] + f[2] / 2) * sx), float((f[1] + f[3] / 2) * sy),
            float(f[2] * sx))


def content_roi(frame, frac=0.05):
    """엣지 밀도로 '내용이 실제로 있는' 바운딩 박스를 구한다."""
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    g = cv2.GaussianBlur(g, (3, 3), 0)
    mag = cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3),
                        cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3))
    thr = max(24.0, float(np.percentile(mag, 90)))
    mask = (mag >= thr).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8))
    h, w = mask.shape

    def span(prof):
        peak = float(prof.max())
        if peak <= 0:
            return 0, len(prof)
        idx = np.where(prof >= peak * frac)[0]
        return int(idx[0]), int(idx[-1] + 1)

    x0, x1 = span(mask.sum(axis=0).astype(np.float32))
    y0, y1 = span(mask.sum(axis=1).astype(np.float32))
    return [x0, y0, max(x1 - x0, 1), max(y1 - y0, 1)]


def fit_rect_916(cx, cy, want_w, w, h):
    """중심 (cx,cy) 에 9:16 크롭 박스를 물린다. 프레임 밖으로 안 나가게 클램프."""
    cw = min(want_w, h * AR, w)
    ch = cw / AR
    if ch > h:
        ch = h
        cw = ch * AR
    x = min(max(cx - cw / 2, 0.0), w - cw)
    y = min(max(cy - ch / 2, 0.0), h - ch)
    return [int(round(x)), int(round(y)), int(round(cw)), int(round(ch))]


def analyze_shot(cap, detector, fps, w, h, t0, t1, min_crop_w, fit_ratio):
    """샷 하나의 대표 프레임들을 보고 (mode, rect, reason) 을 정한다."""
    ts = [t0 + (t1 - t0) * p for p in (0.25, 0.5, 0.75)]
    faces, rois = [], []
    for t in ts:
        frame = grab(cap, fps, t)
        if frame is None:
            continue
        f = detect_face(detector, frame, w, h)
        if f:
            faces.append(f)
        rois.append(content_roi(frame))
    if not rois:
        return "band", [0, 0, w, h], "프레임 판독 실패 — 전체 보기로 폴백"

    # 얼굴이 과반 프레임에서 잡히고 충분히 크면 토킹헤드로 본다
    if len(faces) >= max(1, len(rois) // 2 + 1) and \
            np.median([f[2] for f in faces]) >= w * 0.10:
        cx = float(np.median([f[0] for f in faces]))
        cy = float(np.median([f[1] for f in faces]))
        fw = float(np.median([f[2] for f in faces]))
        rect = fit_rect_916(cx, cy + h * 0.12, h * AR, w, h)
        return "fill", rect, f"얼굴 폭 {fw:.0f}px — 토킹헤드"

    # 자료화면: 여백을 뺀 실제 내용 박스를 밴드에 얹는다
    roi = np.median(np.array(rois, dtype=np.float32), axis=0)
    rx, ry, rw, rh = [float(v) for v in roi]
    pad = 0.02
    rx = max(0.0, rx - w * pad)
    ry = max(0.0, ry - h * pad)
    rw = min(w - rx, rw + 2 * w * pad)
    rh = min(h - ry, rh + 2 * h * pad)
    ratio = (rw * rh) / float(w * h)
    if ratio >= 0.90:
        return "band", [0, 0, w, h], "자료가 화면 전체 — 여백 없음"
    return ("band", [int(rx), int(ry), int(rw), int(rh)],
            f"자료 박스 {int(rw)}x{int(rh)} (화면의 {ratio*100:.0f}%)")


def apply_focus(shots, focus, w, h, min_crop_w):
    """plan.json 의 focus 로 자동 판정을 덮어쓴다. 겹치면 샷을 쪼갠다.

    mode: "band"(기본) 는 rect 를 그대로 밴드에 얹는다 — 9:16 으로 억지로 늘리지
    않으므로 자료가 잘리지 않는다. "fill" 은 9:16 으로 맞춰 화면을 꽉 채운다.
    옛 이름 zoom/fit 은 band 로 읽는다(fit 은 rect 를 프레임 전체로).
    """
    if not focus:
        return shots
    for fc in focus:
        ft0, ft1 = float(fc["t0"]), float(fc["t1"])
        mode = fc.get("mode", "band")
        rect = fc.get("rect")
        if mode == "fit":
            mode, rect = "band", [0, 0, w, h]
        elif mode == "zoom":
            mode = "band"
        if mode == "fill":
            if not rect:
                raise ValueError(f"focus {ft0}-{ft1}: fill 인데 rect 가 없다")
            x, y, rw, rh = [float(v) for v in rect]
            rect = fit_rect_916(x + rw / 2, y + rh / 2,
                                max(rw, rh * AR, min_crop_w), w, h)
        else:
            if not rect:
                rect = [0, 0, w, h]
            x, y, rw, rh = [int(round(float(v))) for v in rect]
            x, y = max(0, x), max(0, y)
            rect = [x, y, min(rw, w - x), min(rh, h - y)]
        new = []
        for sh in shots:
            s0, s1 = sh["t0"], sh["t1"]
            if s1 <= ft0 or s0 >= ft1:
                new.append(sh)
                continue
            if s0 < ft0:
                new.append(dict(sh, t1=ft0))
            new.append(dict(sh, t0=max(s0, ft0), t1=min(s1, ft1), mode=mode,
                            rect=rect, reason=f"focus 수동 지정({mode})",
                            manual=True))
            if s1 > ft1:
                new.append(dict(sh, t0=ft1))
        shots = [s for s in new if s["t1"] - s["t0"] > 0.04]
    merged = [shots[0]]
    for sh in shots[1:]:
        p = merged[-1]
        if (sh.get("manual") and p.get("manual") and sh["mode"] == p["mode"]
                and sh["rect"] == p["rect"] and abs(sh["t0"] - p["t1"]) < 0.02):
            p["t1"] = sh["t1"]
        else:
            merged.append(sh)
    return merged


def main():
    ap = argparse.ArgumentParser(description="장면별 9:16 레이아웃 결정")
    ap.add_argument("--in", dest="in_path", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--model", required=True, help="YuNet onnx 경로")
    ap.add_argument("--plan", default=None)
    ap.add_argument("--scene-thresh", type=float, default=0.22)
    ap.add_argument("--min-shot", type=float, default=1.10,
                    help="이보다 짧은 샷은 앞 샷에 흡수한다(초)")
    ap.add_argument("--min-crop-w", type=int, default=0,
                    help="zoom 최소 크롭 폭(px). 0 이면 높이*9/16 의 0.82배")
    ap.add_argument("--fit-ratio", type=float, default=0.90,
                    help="자료 박스가 화면의 이 비율 이상이면 여백 트림을 포기한다")
    ap.add_argument("--kenburns", type=float, default=0.035,
                    help="샷당 켄번즈 확대 증가분(0 이면 끔)")
    args = ap.parse_args()

    w, h, fps, duration = probe(args.in_path)
    # 기본 하한 = 세로 전체를 쓰는 9:16 크롭(720p 기준 405px). 그보다 더 확대하면
    # 1080 폭으로 올릴 때 2.7배를 넘어 슬라이드 글자가 뭉갠다(2026-09-06 실측 판단).
    min_crop_w = args.min_crop_w or int(round(h * AR))
    log(f"[scene_crop] 원본 {w}x{h} {fps:.3f}fps {duration:.2f}s "
        f"min_crop_w={min_crop_w}")

    cuts = detect_scene_cuts(args.in_path, args.scene_thresh)
    cuts += silence_cut_times(args.in_path)
    shots_ts = build_shots(cuts, duration, args.min_shot)
    log(f"[scene_crop] 컷 후보 {len(cuts)}개 -> 샷 {len(shots_ts)}개")

    cap = cv2.VideoCapture(args.in_path)
    if not cap.isOpened():
        raise RuntimeError(f"영상을 열 수 없다: {args.in_path}")
    detector = cv2.FaceDetectorYN.create(args.model, "", (DET_W, DET_H),
                                         0.5, 0.3, 5000)
    detector.setInputSize((DET_W, DET_H))

    shots = []
    for t0, t1 in shots_ts:
        mode, rect, reason = analyze_shot(cap, detector, fps, w, h, t0, t1,
                                          min_crop_w, args.fit_ratio)
        shots.append({"t0": round(t0, 3), "t1": round(t1, 3), "mode": mode,
                      "rect": rect, "reason": reason,
                      "kb": round(args.kenburns, 4)})
    cap.release()

    focus = None
    if args.plan and os.path.exists(args.plan):
        with open(args.plan, "r", encoding="utf-8", errors="ignore") as f:
            focus = json.load(f).get("focus")
    if focus:
        shots = apply_focus(shots, focus, w, h, min_crop_w)
        log(f"[scene_crop] focus {len(focus)}건 적용 -> 샷 {len(shots)}개")

    counts = {}
    for sh in shots:
        counts[sh["mode"]] = counts.get(sh["mode"], 0) + 1
    out = {"src": os.path.abspath(args.in_path), "src_w": w, "src_h": h,
           "fps": fps, "duration": duration, "out_w": OUT_W, "out_h": OUT_H,
           "min_crop_w": min_crop_w, "shots": shots}
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    for sh in shots:
        log(f"  {sh['t0']:7.2f}-{sh['t1']:7.2f} {sh['mode']:4s} "
            f"rect={sh['rect']} {sh['reason']}")
    log(f"[완료] {args.out_json} 샷 {len(shots)}개 {counts}")


if __name__ == "__main__":
    main()
