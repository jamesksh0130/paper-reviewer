# Academic Paper Reviewer

AI 기반 3인 병렬 논문 심사 시스템. PDF/DOCX 논문과 제출 대상 저널·컨퍼런스를 입력하면, 서로 다른 관점을 가진 3명의 AI 리뷰어가 독립적으로 논문을 검토하고 Area Chair 역할의 AI가 최종 판정을 내립니다.

CVPR, NeurIPS, ICML, ICLR, IEEE TPAMI, Nature Machine Intelligence 등 주요 컨퍼런스·저널 심사 기준에 맞춰 평가가 진행됩니다.

## 핵심 구조

단일 AI 리뷰어는 실행할 때마다 결과가 달라지는 일관성 문제가 있어, 실제 학술 심사 프로세스를 모방한 멀티 에이전트 구조로 설계했습니다.

- **검토자 1 (기술 전문가)** — 방법론의 수학적 엄밀성, 알고리즘 설계, 실험의 과학적 타당성
- **검토자 2 (신규성/영향력 전문가)** — 연구의 독창성, SOTA 대비 기여도, 분야 발전 가능성
- **검토자 3 (보수적 학자)** — 논문 완성도, 관련 연구 포괄성, ablation study 충분성을 엄격하게 평가
- **Area Chair (메타 리뷰어)** — 3명의 독립 리뷰를 종합해 합의점·불일치점을 조율하고 Desk Reject부터 Strong Accept까지 최종 판정

세 리뷰어는 서버에서 멀티스레드로 병렬 실행되며, 모든 리뷰가 완료된 후 Area Chair가 종합 판정을 수행합니다.

## 출력 결과

- 리뷰어별 요약 점수표(신규성 / 기술 완성도 / 실험 품질 / 작성 품질 / 중요도)
- 핵심 강점 3가지, 핵심 약점 3가지, 저자에게 보내는 핵심 질문
- Area Chair 탭에서 3인 점수 비교표, 합의/불일치 사항, 최종 결정 및 수정 방향 확인

## 기술 스택

- **Backend**: FastAPI + Server-Sent Events(SSE) 스트리밍
- **병렬 처리**: Python `threading` + `queue`로 3개 리뷰어 동시 실행
- **AI 모델**: OpenRouter API (Meta LLaMA 3.3 70B, NVIDIA Nemotron Super 120B, Nous Hermes 3 405B 등), 모델 장애 시 자동 폴백 체인
- **문서 파싱**: `pdfplumber`(PDF), `python-docx`(DOCX)
- **Frontend**: 바닐라 JavaScript + marked.js, 4개 탭 UI(최종 판정 / 검토자 1·2·3), 스트리밍 중 실시간 점수 시각화

## 실행 방법

```bash
pip install -r requirements.txt
cp .env.example .env  # API 키 입력
./start.sh            # http://localhost:8000
```

## 참고

AI가 실제 리뷰어를 대체하거나 게재 가능성을 정확히 예측할 수는 없지만, 제출 전 논문의 논리적 빈틈을 발견하고 저자가 자신의 글을 더 객관적으로 바라보도록 돕는 사전 리뷰어 역할을 합니다.
