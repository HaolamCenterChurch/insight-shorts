#!/usr/bin/env python3
"""insight-shorts 오케스트레이터.

stage a : 구간 추출 -> 무음 제거 -> DTW 전사 -> 장면별 레이아웃 결정(scene.json)
stage b : 중앙 박스 자막 ASS -> 9:16 렌더 -> 재전사 유사도 검증

검증된 부분(구간 추출·무음 제거·DTW 전사·유사도 검증)은 shorts_v2 모듈을 그대로
호출한다. 달라지는 건 '무엇을 어떻게 보여줄지'(scene_crop/render_insight)와
'자막을 어떻게 그릴지'(make_ass_box) 뿐이다.
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_pipeline as v2  # noqa: E402  (transcribe_words / run_module 재사용)

YUNET_MODEL = v2.YUNET_MODEL


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def run_local(script, args_list):
    cmd = [sys.executable, os.path.join(HERE, script)] + args_list
    log(f"[run_insight] 실행: {script} {' '.join(args_list)}")
    subprocess.run(cmd, check=True)


def stage_scene(plan, plan_path, workdir, opts):
    """장면 레이아웃만 다시 계산한다. plan.json 의 focus 를 고치고 재실행하는 용도."""
    slug = plan["slug"]
    master = os.path.join(workdir, f"{slug}_master.mov")
    scene = os.path.join(workdir, f"{slug}_scene.json")
    sc = ["--in", master, "--out-json", scene, "--model", YUNET_MODEL,
          "--plan", plan_path, "--scene-thresh", str(opts.scene_thresh),
          "--fit-ratio", str(opts.fit_ratio), "--kenburns", str(opts.kenburns)]
    if opts.min_crop_w:
        sc += ["--min-crop-w", str(opts.min_crop_w)]
    run_local("scene_crop.py", sc)
    return scene


def stage_a(src, plan, plan_path, workdir, opts):
    slug = plan["slug"]
    segments = ";".join(f"{s}-{e}" for s, e in plan["segments"])

    raw = os.path.join(workdir, f"{slug}_raw.mov")
    v2.run_module("extract_segments.py", [
        "--src", src, "--segments", segments, "--out", raw,
        "--workdir", workdir])

    raw_words, _ = v2.transcribe_words(raw, workdir, f"{slug}_raw")

    master = os.path.join(workdir, f"{slug}_master.mov")
    sil = ["--in", raw, "--out", master, "--words", raw_words,
           "--min-silence", str(opts.min_silence), "--pad", "0.12",
           "--keep-gap", "0.06", "--min-gain", "0.40", "--min-keep", "1.20",
           "--workdir", workdir]
    if plan.get("preserve"):
        sil += ["--preserve", ";".join(f"{s}-{e}" for s, e in plan["preserve"])]
    v2.run_module("silence_cut.py", sil)

    master_words, _ = v2.transcribe_words(master, workdir, f"{slug}_master")

    scene = stage_scene(plan, plan_path, workdir, opts)

    with open(master + ".cuts.json", encoding="utf-8") as f:
        duration = json.load(f)["duration"]
    log(f"[stage a 완료] master={master} words={master_words} "
        f"duration={duration:.3f}s scene={scene}")
    return {"master": master, "master_words": master_words, "scene": scene,
            "duration": duration}


def stage_b(plan, workdir, outdir, chunks, opts, state=None):
    slug = plan["slug"]
    master = os.path.join(workdir, f"{slug}_master.mov")
    master_words = os.path.join(workdir, f"{slug}_master.words.json")
    scene = os.path.join(workdir, f"{slug}_scene.json")
    if state:
        master, master_words, scene = (state["master"], state["master_words"],
                                       state["scene"])
        duration = state["duration"]
    else:
        with open(master + ".cuts.json", encoding="utf-8") as f:
            duration = json.load(f)["duration"]

    style = plan.get("style", {})
    ass = os.path.join(workdir, f"{slug}.ass")
    ass_args = [
        "--words", master_words, "--chunks", chunks, "--out", ass,
        "--duration", str(duration),
        "--fs", str(style.get("fs", opts.fs)),
        "--pos-y", str(style.get("pos_y", opts.pos_y)),
        "--max-chars", str(style.get("max_chars", opts.max_chars)),
        "--box", style.get("box", opts.box),
        "--anchor", str(style.get("anchor", opts.anchor))]
    if plan.get("hook_title"):
        ass_args += ["--title", plan["hook_title"],
                     "--title-y", str(style.get("title_y", opts.title_y)),
                     "--title-fs", str(style.get("title_fs", opts.title_fs)),
                     "--title-color", style.get("title_color", opts.title_color),
                     "--title-hl-color", style.get("title_hl_color",
                                                   "&H0000D7FF")]
        if style.get("title_box"):
            ass_args += ["--title-box", style["title_box"]]
    run_local("make_ass_box.py", ass_args)

    os.makedirs(outdir, exist_ok=True)
    final = os.path.join(outdir, f"{slug}.mp4")
    run_local("render_insight.py", [
        "--in", master, "--scene", scene, "--ass", ass, "--out", final,
        "--workdir", workdir,
        "--band-y", str(style.get("band_y", opts.band_y)),
        "--band-h", str(style.get("band_h", opts.band_h)),
        "--bg", style.get("bg", opts.bg),
        "--band-align", style.get("band_align", opts.band_align)])

    script_path = os.path.join(workdir, f"{slug}_script.txt")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(plan.get("script", ""))
    report = os.path.join(outdir, f"{slug}_verify.md")
    v2.run_module("verify_output.py", [
        "--video", final, "--script", script_path, "--out", report,
        "--workdir", workdir])
    log(f"[stage b 완료] 최종본={final} 리포트={report}")


def main():
    ap = argparse.ArgumentParser(description="insight-shorts 파이프라인")
    ap.add_argument("--src", required=True)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--stage", choices=["a", "scene", "b"], default="a")
    ap.add_argument("--chunks", default=None)
    ap.add_argument("--min-silence", type=float, default=0.30)
    ap.add_argument("--scene-thresh", type=float, default=0.22)
    ap.add_argument("--fit-ratio", type=float, default=0.52)
    ap.add_argument("--kenburns", type=float, default=0.035)
    ap.add_argument("--min-crop-w", type=int, default=0)
    ap.add_argument("--fs", type=int, default=96)
    ap.add_argument("--pos-y", type=int, default=1420)
    ap.add_argument("--max-chars", type=int, default=10)
    ap.add_argument("--box", default="&H1A000000")
    ap.add_argument("--band-y", type=int, default=480)
    ap.add_argument("--band-h", type=int, default=800)
    ap.add_argument("--bg", choices=["blur", "black"], default="black")
    ap.add_argument("--band-align", choices=["center", "bottom"], default="bottom")
    ap.add_argument("--anchor", type=int, choices=[2, 5], default=5)
    ap.add_argument("--title-y", type=int, default=360)
    ap.add_argument("--title-fs", type=int, default=120)
    ap.add_argument("--title-color", default="&H00FFFFFF")
    args = ap.parse_args()

    # ★shorts_v2 모듈들은 concat 목록에 상대경로를 쓴다 — 상대 outdir 로 부르면
    #   'v2/out/_work/v2/out/_work/seg_000.mov' 처럼 두 번 붙어 실패한다(2026-09-06 실측).
    args.src = os.path.abspath(args.src)
    args.plan = os.path.abspath(args.plan)
    args.outdir = os.path.abspath(args.outdir)
    if args.chunks:
        args.chunks = os.path.abspath(args.chunks)

    with open(args.plan, encoding="utf-8", errors="ignore") as f:
        plan = json.load(f)
    workdir = os.path.join(args.outdir, "_work")
    os.makedirs(workdir, exist_ok=True)

    if args.stage == "a":
        state = stage_a(args.src, plan, args.plan, workdir, args)
        if args.chunks:
            stage_b(plan, workdir, args.outdir, args.chunks, args, state=state)
        else:
            print(json.dumps({"master_words": state["master_words"],
                              "scene": state["scene"],
                              "duration": state["duration"]},
                             ensure_ascii=False))
    elif args.stage == "scene":
        scene = stage_scene(plan, args.plan, workdir, args)
        print(json.dumps({"scene": scene}, ensure_ascii=False))
    else:
        if not args.chunks:
            raise ValueError("--stage b 에는 --chunks 가 필요하다")
        stage_b(plan, workdir, args.outdir, args.chunks, args)


if __name__ == "__main__":
    main()
