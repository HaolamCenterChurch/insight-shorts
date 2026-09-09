#!/usr/bin/env python3
"""insight-shorts: 화면 중앙 · 큰 한글 단독 자막 · 검은 박스 ASS 생성.

설교 쇼츠(shorts_v2/make_ass.py)와 다른 점 (오너 지시 2026-09-06):
  · 영문 2단 없음 — 한글 한 줄만
  · 하단 MarginV 470 이 아니라 **화면 중앙** \\an5\\pos(540,Y)
  · 글씨를 더 크게 (기본 78pt)
  · **그림자 금지**. 대신 BorderStyle=3 불투명 박스에 글자를 넣는다

타이밍 정렬(청크 <-> 단어 타임스탬프)은 검증된 shorts_v2/make_ass.py 로직을
그대로 가져다 쓴다. 그래서 check_chunks.py 기계 검증도 동일하게 통과해야 한다.
"""
import argparse
import json
import os
import sys

import re

def normalize(text):
    """한글/영숫자만 남긴 정규화 문자열."""
    return re.sub(r"[^0-9A-Za-z가-힣]", "", text or "")

def fmt_time(sec):
    if sec < 0:
        sec = 0.0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    cs = int(round((sec - int(sec)) * 100))
    if cs >= 100:
        cs -= 100
        s += 1
        if s >= 60:
            s -= 60
            m += 1
            if m >= 60:
                m -= 60
                h += 1
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def match_chunks_to_words(words, chunks):
    """길이 기반 소비로 chunk 별 시작/끝을 단어 타임스탬프에서 구한다."""
    norm_words = [normalize(w.get("text", "")) for w in words]
    w_idx = 0
    n_words = len(words)
    results = []
    for chunk in chunks:
        target_len = len(normalize(chunk.get("stt") or chunk.get("ko", "")))
        first_idx = w_idx
        while first_idx < n_words and not norm_words[first_idx]:
            first_idx += 1
        consumed = 0
        last_idx = w_idx
        if target_len == 0:
            results.append((None, None))
            continue
        while w_idx < n_words and consumed < target_len:
            consumed += len(norm_words[w_idx])
            last_idx = w_idx
            w_idx += 1
        if first_idx >= n_words:
            first_idx = last_idx = n_words - 1
        start = words[first_idx]["t0"] if n_words else 0.0
        end = words[last_idx]["t1"] if n_words else 0.0
        results.append((start, end))
    return results

HEADER = """[Script Info]
Title: insight-shorts subtitles
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Box,{font},{fs},&H00FFFFFF,&H000000FF,{box},&H00000000,-1,0,0,0,100,100,0,0,3,{pad},0,5,40,40,0,1
Style: Title,{font},{tfs},{tcolor},&H000000FF,{tbox},&H00000000,-1,0,0,0,100,100,0,0,3,{tpad},0,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def wrap_ko(text, max_chars):
    """긴 줄을 가운데 근처 공백에서 두 줄로 나눈다(박스 폭이 화면을 넘지 않게)."""
    text = (text or "").strip()
    if len(text) <= max_chars:
        return [text]
    mid = len(text) // 2
    spaces = [i for i, ch in enumerate(text) if ch == " "]
    if spaces:
        cut = min(spaces, key=lambda i: abs(i - mid))
        first, second = text[:cut].strip(), text[cut + 1:].strip()
    else:
        first, second = text[:mid].strip(), text[mid:].strip()
    if len(second) > max_chars:  # 3줄이 되어야 할 만큼 길면 그대로 둔다
        return [first] + wrap_ko(second, max_chars)
    return [first, second]


def main():
    ap = argparse.ArgumentParser(description="중앙 박스 한글 자막 ASS 생성")
    ap.add_argument("--words", required=True)
    ap.add_argument("--chunks", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("--font", default="Apple SD Gothic Neo")
    ap.add_argument("--fs", type=int, default=96, help="한글 글자 크기(pt)")
    ap.add_argument("--pos-y", type=int, default=1420,
                    help="자막 중심 Y (1920 기준, 기본 1420: 자료화면 하단 Y=1280 아래 순검정 영역)")
    ap.add_argument("--box", default="&H1A000000",
                    help="박스 색 &HAABBGGRR — AA 00 이 완전 불투명")
    ap.add_argument("--pad", type=float, default=14.0, help="박스 여백(px)")
    ap.add_argument("--max-chars", type=int, default=10,
                    help="한 줄 최대 글자 수 — 넘으면 두 줄로 나눈다")
    ap.add_argument("--title", default=None,
                    help="영상 내내 상단에 띄울 고정 제목. '|' 로 나누면 두 줄이 되고 "
                         "둘째 줄은 --title-hl-color 로 강조된다(오너 지시 2026-09-07)")
    ap.add_argument("--title-hl-color", default="&H0000D7FF",
                    help="제목 둘째 줄 색(기본 골드)")
    ap.add_argument("--title-y", type=int, default=360,
                    help="제목 중심 Y (1920 기준, 기본 360: 자료 상단과 자연스러운 여백 밀착)")
    ap.add_argument("--title-fs", type=int, default=120,
                    help="제목 글자 크기(pt, 기본 120)")
    ap.add_argument("--title-color", default="&H00FFFFFF",
                    help="제목 첫째 줄 색(기본 순백)")
    ap.add_argument("--title-box", default="&H00000000",
                    help="제목 박스 색(기본: &H00000000 완전불투명 검정). 검정 배경에서는 "
                         "글자만 깔끔하게 노출")
    ap.add_argument("--title-pad", type=float, default=12.0)
    ap.add_argument("--title-max-chars", type=int, default=16,
                    help="제목 한 줄 최대 글자 수 — 넘으면 두 줄로 나눈다")
    ap.add_argument("--anchor", type=int, choices=[2, 5], default=5,
                    help="자막 기준점. 5=중심(기존) / 2=아랫변 고정 — 두 줄이 되어도 "
                         "자막 아랫변이 그대로라 자료 위에 얹기 좋다")
    ap.add_argument("--hl-color", default="&H0000D7FF",
                    help='hl:true 청크 글자색 (기본 골드)')
    args = ap.parse_args()

    with open(args.words, "r", encoding="utf-8", errors="ignore") as f:
        words = json.load(f)
    with open(args.chunks, "r", encoding="utf-8", errors="ignore") as f:
        chunks = json.load(f)
    if not chunks:
        raise ValueError("chunks 가 비어 있다")

    spans = match_chunks_to_words(words, chunks)
    for i, (s, _) in enumerate(spans):
        if s is None:
            prev_e = spans[i - 1][1] if i > 0 and spans[i - 1][1] is not None else 0.0
            spans[i] = (prev_e, prev_e)

    starts = [s for s, _ in spans]
    ends = [e for _, e in spans]
    starts[0] = 0.0
    for i in range(len(spans) - 1):   # 무간극: end[i] = start[i+1]
        ends[i] = starts[i + 1]
    ends[-1] = args.duration

    lines = [HEADER.format(font=args.font, fs=args.fs, box=args.box,
                           pad=f"{args.pad:.1f}", tfs=args.title_fs,
                           tcolor=args.title_color,
                           tbox=(args.title_box or args.box),
                           tpad=f"{args.title_pad:.1f}")]
    if args.title:
        if "|" in args.title:      # 손으로 나눈 두 줄 — 둘째 줄만 강조색
            l1, l2 = [s.strip() for s in args.title.split("|", 1)]
            title_text = l1 + r"\N{\c" + args.title_hl_color + "}" + l2
        else:
            title_text = r"\N".join(wrap_ko(args.title, args.title_max_chars))
        lines.append(
            f"Dialogue: 0,{fmt_time(0.0)},{fmt_time(args.duration)},Title,,0,0,0,,"
            + r"{\an5\pos(540," + str(args.title_y) + ")}" + title_text + "\n")
    n_wrapped = 0
    for chunk, s, e in zip(chunks, starts, ends):
        if e <= s:
            e = s + 0.01
        parts = wrap_ko(chunk.get("ko", ""), args.max_chars)
        if len(parts) > 1:
            n_wrapped += 1
        text = r"\N".join(parts)
        tags = r"{\an" + str(args.anchor) + r"\pos(540," + str(args.pos_y) + ")"
        if chunk.get("hl"):
            tags += r"\c" + args.hl_color
        tags += "}"
        lines.append(
            f"Dialogue: 0,{fmt_time(s)},{fmt_time(e)},Box,,0,0,0,,{tags}{text}\n")

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("".join(lines))
    log(f"[완료] {os.path.basename(args.out)} 블록 {len(chunks)}개 "
        f"(두 줄 {n_wrapped}개), 마지막 종료={ends[-1]:.3f}s, "
        f"{args.fs}pt 중앙 Y={args.pos_y} 박스={args.box}")


if __name__ == "__main__":
    main()
