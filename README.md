# 🌏 인사이트 쇼츠 (Insight Shorts)

> **자료화면(슬라이드·지도·차트·뉴스기사) 위주의 해설·강의 영상 하나로 9:16 세로 쇼츠 완성본 MP4와 썸네일을 자동 생성하는 AI 에이전트 스킬 & 파이프라인**

---

## 💡 기획 의도와 핵심 차이

기존의 숏폼 자동화 도구(`shorts-autopilot` 등)는 말하는 사람의 얼굴을 인식해 인물을 따라가는(Face Tracking) 방식입니다.  
하지만 **국제정세, 시사 평론, 학술 강의, 브리핑 영상**은 인물이 아니라 **말하는 그 순간의 자료(슬라이드, 지도, 통계 그래프, 뉴스 헤드라인, 문서)**를 시청자에게 명확히 보여주는 것이 본질입니다.

`insight-shorts`는 가로 16:9 자료를 무리하게 세로로 잘라먹지 않고, **와이드 밴드 확대 배치 + 순검정 여백 + 메인 컨텐츠를 100% 가리지 않는 완전 비간섭 자막**으로 제작하여 전달력을 극대화합니다.

---

## 🌟 5대 핵심 기능 (2026-09-08 정본 스펙)

1. **완전 비간섭 자막 (Non-overlapping Subtitles)**
   - 자료화면 하단선(Y=1280) 아래 순검정 영역(`pos_y=1420`, `an5`)에 자막을 배치합니다.
   - 자막이 슬라이드, 도표, 인용문, 지도, 인물 등 메인 자료를 단 1%도 가리지 않습니다.
   - 그림자 없는 순수 `BorderStyle=3` 검은 박스(90% 불투명)로 높은 시인성을 보장합니다.

2. **상단 120pt 대형 훅 타이포그래피 (120pt Hero Title)**
   - 영상 상단에 120pt 초대형 2단 타이틀을 고정 노출하여 피드 스크롤 중 시선을 즉각 사로잡습니다.
   - 제목과 자료화면 상단 사이의 여백을 최적화(`title_y=360`)하여 과도한 빈 공간 없이 컨텐츠와 자연스럽게 밀착됩니다.
   - `|` 구분자를 기준으로 둘째 줄은 골드(`#00D7FF`) 컬러로 자동 강조됩니다.

3. **이상 컷(글리치) 안정화 엔진 (Visual Cut Stabilization)**
   - 원본 영상에 0.3~1.5초간 맥락 없이 번쩍이는 AI 플래시 이미지, 도로 폭파 직전 순간 컷, 순검정 암전 프레임, 엉뚱한 이모지 그래픽, 스튜디오 마이크 잔여 컷 등을 식별합니다.
   - 굳이 화면이 바뀔 필요가 없는 구간은 **이전의 자연스러운 관련 자료화면을 연장·유지(`Hold Previous Frame`)**하도록 클린 마스터(`clean_master.mov`)를 자동 생성하여 영상의 완성도를 비약적으로 높입니다. (오디오는 `-c:a copy`로 100% 무손실 동기화 보존)

4. **음성 원문 100% 일치(Verbatim) 재전사 & 전문 용어 교정**
   - 사람이 임의로 요약·축약한 대본을 배제하고, Whisper large-v3 기반으로 화자의 실제 음성을 토큰 단위로 정밀 전사합니다.
   - 화자가 말한 단어와 화면의 자막이 100% 일치하며, STT 특유의 군사·신학·시사 전문 용어 오인식을 철저히 사전 교정합니다.
   - `check_chunks.py` 기계 검증(`✅ 일치`)을 통과해야만 렌더링을 허용하는 Hard Gate를 적용합니다.

5. **포토제닉 썸네일 & 다중 플랫폼 안전영역 가이드**
   - 자막이 번인되지 않은 클린 마스터에서 가장 해상도와 구도가 좋은 프레임을 자동 선별합니다.
   - 유튜브 쇼츠(9:16 전체)는 물론, 인스타그램 릴스 탭(3:4) 및 프로필 피드(4:5) 격자에서도 텍스트가 잘리지 않는 전용 썸네일과 가이드 이미지를 함께 생성합니다.

---

## 📦 설치 및 요구사항

### 1. 시스템 도구
- **FFmpeg & FFprobe**: 비디오 합성 및 필터링
  - macOS: `brew install ffmpeg`
  - Ubuntu/Debian: `sudo apt install ffmpeg`
- **Whisper CLI & 모델**: 음성 정밀 전사
  - [whisper.cpp](https://github.com/ggerganov/whisper.cpp) 빌드 바이너리 (`whisper-cli`)
  - 모델: `ggml-large-v3.bin` (권장)
- **YuNet ONNX** (옵션): 토킹헤드 인물 검출용 모델 (`yunet.onnx`)

### 2. 환경변수 설정 (선택 사항)
시스템 기본 경로(`which ffmpeg`) 외에 별도 빌드본이나 모델 경로를 지정할 수 있습니다:
```bash
export FFMPEG_PATH="/opt/homebrew/bin/ffmpeg"
export WHISPER_BIN="/path/to/whisper.cpp/build/bin/whisper-cli"
export WHISPER_MODEL="/path/to/models/ggml-large-v3.bin"
export YUNET_MODEL="/path/to/models/yunet.onnx"
```

### 3. 파이썬 환경 설정
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 🤖 AI 에이전트 스킬로 등록 및 사용

본 저장소는 **Google Antigravity**, **Gemini CLI**, **Claude Code**, **Cursor** 등 다양한 AI 에이전트 환경에서 즉시 로드할 수 있는 표준 `SKILL.md` 명세를 포함하고 있습니다.

### 1. Google Antigravity / Gemini CLI
저장소를 에이전트 스킬 디렉토리에 복사하거나 심볼릭 링크를 생성합니다:
```bash
# 글로벌 스킬로 등록
git clone https://github.com/HaolamCenterChurch/insight-shorts.git ~/.gemini/antigravity-cli/skills/insight-shorts

# 또는 프로젝트 워크스페이스 전용 스킬로 등록
git clone https://github.com/HaolamCenterChurch/insight-shorts.git .agents/skills/insight-shorts
```
- **발동 트리거**:  
  `"시사 쇼츠 만들어줘"`, `"정세 쇼츠"`, `"인사이트 쇼츠"`, `"자료화면 쇼츠"`, `"강의 영상 쇼츠"`

### 2. Claude Code / Cursor / Windsurf
에이전트에게 `SKILL.md` 파일을 참조하도록 프롬프트를 전달하면 워크플로우에 따라 자동으로 파이프라인을 실행합니다.

---

## 🚀 파이프라인 실행 워크플로우

```text
Phase 0: 원본 전사 (Whisper large-v3)
    ↓
Phase 1: 주장 → 근거(자료) → 관점 3안 기획 (H-E-S 구조)
    ↓
Phase 2: Stage A (구간 추출 → 무음 제거 → DTW 글자 타임스탬프)
    ↓
Phase 3: 이상 컷(글리치) 제거 & 자료 포커스(Focus) 영역 지정
    ↓
Phase 4: 자막 청크 작성 & 100% 원문 스트림 기계 검증 (check_chunks)
    ↓
Phase 5: Stage B (순검정 완전 비간섭 ASS 자막 합성 & 9:16 렌더링 & 유사도 검증)
    ↓
Phase 6: 클린 마스터 기반 2단 훅 썸네일 생성 (YouTube + Instagram)
    ↓
Phase 7: 게이트 검증 및 최종 브리핑
```

### 빠른 실행 예시

1. **Stage A 실행 (무음 제거 및 DTW 전사)**:
   ```bash
   python3 scripts/run_insight.py \
     --src "lecture_video.mp4" \
     --plan examples/plan_example.json \
     --outdir "out/" \
     --stage a
   ```

2. **자막 원문 일치 검증**:
   ```bash
   python3 scripts/check_chunks.py \
     --words "out/_work/{slug}_master.words.json" \
     --chunks "out/_work/chunks.json"
   ```

3. **Stage B 실행 (최종 영상 렌더링)**:
   ```bash
   python3 scripts/run_insight.py \
     --src "lecture_video.mp4" \
     --plan examples/plan_example.json \
     --outdir "out/" \
     --stage b \
     --chunks "out/_work/chunks.json"
   ```

4. **썸네일 추출 및 제작**:
   ```bash
   python3 scripts/extract_frames_insight.py \
     --master "out/_work/{slug}_master.mov" \
     --scene "out/_work/{slug}_scene.json" \
     --times 5 15 25 --outdir "out/_work/frames" --prefix "A"

   python3 scripts/generate_thumbnail.py --mode both \
     --frame "out/_work/frames/A_005.00.jpg" --badge "한반도 안보" \
     --l1 "북한은 우리를" --l2 "적으로 규정했다" --sub "DMZ 100km 전술도로" \
     --out-yt "out/{slug}_thumb_youtube.jpg" \
     --out-insta "out/{slug}_thumb_instagram.jpg" \
     --out-guide "out/{slug}_thumb_instagram_guide.jpg"
   ```

---

## 📂 저장소 구조

```text
insight-shorts/
├── SKILL.md                 # Antigravity/Agent 표준 스킬 명세서
├── README.md                # 저장소 소개 및 사용 가이드
├── LICENSE                  # MIT License
├── requirements.txt         # 파이썬 의존성 패키지
├── examples/
│   ├── plan_example.json    # 레이아웃/스타일/포커스 기획안 예시
│   └── chunks_example.json  # 음성 원문 일치 자막 청크 예시
└── scripts/
    ├── run_insight.py       # 메인 파이프라인 오케스트레이터
    ├── scene_crop.py        # 컷 감지 및 와이드 밴드/크롭 레이아웃 계산
    ├── make_ass_box.py      # 비간섭 검은 박스 ASS 자막 생성기
    ├── render_insight.py    # FFmpeg 9:16 합성 렌더러
    ├── extract_frames_insight.py # 클린 마스터 썸네일 프레임 추출기
    ├── check_insight.py     # 하드 게이트 검증 스크립트
    ├── check_chunks.py      # 음성 전사 스트림 100% 일치 검사기
    ├── extract_segments.py  # 비디오 세그먼트 고속 추출기
    ├── silence_cut.py       # 자연스러운 무음 구간 컷 편집기
    ├── verify_output.py     # 최종본 Whisper 재전사 유사도 검증기
    └── generate_thumbnail.py# 유튜브/인스타그램 안전영역 썸네일 생성기
```

---

## 📄 라이선스
MIT License (Copyright (c) 2026 Haolam Center Church)
