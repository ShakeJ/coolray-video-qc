# Coolray Video QC — 영상·자막 검수 스킬

로컬 영상과 자막을 검사해 JSON 보고서와 검수 프레임을 남기는 작은 스킬입니다. 계정·API 키 없이 실행하며 원본을 수정하거나 재생하지 않습니다. 버전 0.1.0 / MIT.

## 기능과 준비

- 영상 디코드 오류, 지정 크기·fps·길이, 오디오 누락, 영상·음성 스트림의 시작/끝 차이 확인.
- 암전·정지·무음 후보, 음량과 색상 메타데이터 확인, SDR 검수 프레임과 비교 시트 추출.
- SRT·WebVTT·밀리초 JSON 자막의 시간 오류·겹침·영상 범위 초과·읽기 속도·줄 길이 검사.
- 한국어·어린이 한국어·라틴 문자 프리셋. 기준은 조절 가능한 참고값입니다.

Python 3.10 이상이 필요합니다. 영상 검사에는 PATH에 설치된 FFmpeg와 ffprobe가 추가로 필요합니다. pip 패키지나 생성 서비스는 필요하지 않습니다. macOS에서 직접 검증했으며 Linux CI 설정을 포함했습니다. Windows는 검증하지 않았습니다.

## 바로 실행

압축을 푼 `coolray-video-qc` 폴더에서 실행합니다.

```bash
python3 scripts/captions.py examples/clean.srt --duration 3 --profile ko
python3 scripts/captions.py examples/overlap.srt --duration 3 --profile ko
```

두 번째 예제는 일부러 자막을 겹쳐 놓아 종료코드 1이 나옵니다.

```bash
python3 examples/make_demo.py --out /tmp/coolray-video-qc-demo
python3 scripts/media_audit.py /tmp/coolray-video-qc-demo/demo.mp4 \
  --out /tmp/coolray-video-qc-demo/review --expect-size 320x180 --require-audio
```

합성 패턴과 톤을 파일로 만들 뿐 소리는 재생하지 않습니다. `review/report.json`과 `review/contact-sheet.jpg`를 확인합니다. 재실행할 때는 새 출력 위치를 사용합니다.

## 스킬 설치

압축을 푼 `coolray-video-qc` 폴더가 있는 상위 디렉터리에서 원하는 명령을 실행합니다. 기존 설치는 덮어쓰지 않습니다.

Codex 프로젝트에 설치:

```bash
mkdir -p .agents/skills
python3 -c 'import shutil; shutil.copytree("coolray-video-qc", ".agents/skills/coolray-video-qc")'
```

Claude Code 개인 스킬로 설치:

```bash
python3 -c 'from pathlib import Path; import shutil; shutil.copytree("coolray-video-qc", Path.home()/".claude/skills/coolray-video-qc")'
```

발견되지 않으면 새 세션에서 확인합니다. “coolray-video-qc로 이 영상과 자막을 검사하고 오류·경고·미확인 항목을 알려주세요”라고 요청합니다. Codex는 `$coolray-video-qc`, Claude Code는 `/coolray-video-qc`로 호출할 수 있습니다.

## 결과 해석

- 종료코드 0: 수행한 검사에서 구조 오류 없음. 경고는 남을 수 있습니다.
- 종료코드 1: 구조 오류 발견.
- 종료코드 2: 입력·의존성 문제 또는 검사 미완료.

의도적 정지·암전·쉼도 경고에 잡힙니다. 구조 오류 0이 재미·발음·립싱크·권리·실제 원본 화질의 합격을 뜻하지 않습니다. 프레임 추출과 실제 시각 검수도 구분합니다. HDR은 SDR JPEG가 오해를 만들 수 있어 자동 추출하지 않습니다. `--metadata-only`는 전체 디코드·신호 검사·프레임 추출을 생략합니다.

영상은 첫 번째 일반 비디오와 첫 번째 오디오 스트림, 자막은 단일 트랙을 검사합니다. 보고서에는 원본 경로·메타데이터·자막·추출 이미지가 들어갑니다. 외부 공유 시 내용을 확인합니다.

테스트·배포 명령은 [영문 README](README.md), 자세한 결과는 [결과 해석](references/reports.md), 옵션은 각 스크립트의 `--help`를 참고하세요. 영상 제작·업로드 기능은 포함하지 않습니다.
