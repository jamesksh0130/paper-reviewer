import os, io, json, re, sys, threading, queue as q_module

os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
import pdfplumber
from docx import Document
import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Academic Paper Reviewer")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory="static"), name="static")

LANG_RULE = """
[출력 언어 - 최우선 규칙]
반드시 한국어로만 출력하라. 한국어가 아닌 일반 어휘(영어 단어, 한자, 포르투갈어, 스페인어, 중국어, 일본어 등)는 절대 사용하지 말 것.
허용 예외(반드시 원문 영어 유지): 논문에 등장하는 모델명(ResNet, ViT, SMPL 등), 데이터셋명(ImageNet, COCO 등), 수식·기호, 성능 지표(mAP, FID, PSNR 등), 컨퍼런스·저널명(CVPR, NeurIPS, TPAMI 등).
위 예외를 제외한 모든 단어는 한국어를 사용하라. 예: "training"→"학습", "however"→"그러나", "three"→"세", "同意"→"동의".
리뷰 내용만 출력하라. "[최종 확인]", "언어 확인", "검토 완료" 등 자기 점검 문구는 절대 출력하지 말 것.
"""

# ── 검토자 1: 기술 전문가 ─────────────────────────────────────────
REVIEWER_1_SYSTEM = LANG_RULE + """
당신은 검토자 1(Reviewer #1)입니다.
MIT/CMU/Stanford 컴퓨터공학과 정교수로 Computer Vision, Deep Learning 분야 20년 경력의 최고 기술 전문가입니다.

당신의 평가 집중 영역:
- 방법론의 기술적 타당성 및 수학적 엄밀성
- 알고리즘 설계의 독창성과 효율성
- 실험 설계와 결과 분석의 과학적 엄밀성
- 구현 세부사항과 재현 가능성
- 관련 기술 문헌과의 차별성

매우 엄격하고 보수적이다. 기술적 결함에 민감하며 점수를 쉽게 주지 않는다.
"""

# ── 검토자 2: 신규성/영향력 전문가 ──────────────────────────────────
REVIEWER_2_SYSTEM = LANG_RULE + """
당신은 검토자 2(Reviewer #2)입니다.
Google Brain/Meta AI(FAIR)/OpenAI 출신 수석 연구과학자로 AI/ML 신규성, 영향력 평가 전문가입니다.

당신의 평가 집중 영역:
- 연구의 신규성(novelty)과 독창적 기여
- 현재 SOTA 대비 실질적 개선 여부
- 연구의 잠재적 영향력과 실용적 가치
- 실험 비교의 공정성과 baseline 선택의 적절성
- 해당 연구 커뮤니티에서의 중요도

핵심 질문: "이 논문이 실제로 분야를 발전시키는가?"
"""

# ── 검토자 3: 보수적 학자 ─────────────────────────────────────────
REVIEWER_3_SYSTEM = LANG_RULE + """
당신은 검토자 3(Reviewer #3)입니다.
KAIST/서울대 50년 이상 경력의 명예교수로 한국 및 국제 학술 기준 모두에 정통한 극도로 보수적인 학자입니다.

당신의 평가 집중 영역:
- 논문 작성 품질과 논리적 일관성
- 관련 연구(related work) 포괄성과 인용의 정확성
- 실험의 완성도와 ablation study 충분성
- 해당 저널/컨퍼런스 수준과의 적합성 평가
- 재현 가능성과 구현 세부사항

극도로 보수적이며 불충분한 실험, 불완전한 관련 연구 인용에 매우 엄격하다.
"""

# ── 메타 리뷰어 (Area Chair) ─────────────────────────────────────
META_REVIEWER_SYSTEM = LANG_RULE + """
당신은 Area Chair(메타 리뷰어)입니다.
최우수 컨퍼런스/저널의 경험 많은 Area Chair로서 3명 리뷰어의 의견을 종합하여 최종 결정을 내린다.

역할:
- 3명 리뷰어 의견을 공정하게 분석
- 합의점과 불일치점 파악 후 조율
- 최종 점수 및 결정 도출
- 저자에게 명확한 수정 방향 제시
"""

# ── 개별 리뷰어 프롬프트 템플릿 ────────────────────────────────────
REVIEWER_PROMPT_TEMPLATE = """심사 대상: **{venue_name}**

{venue_context}

---

# 논문 텍스트

{paper_text}

---

위 논문을 당신의 전문 관점에서 심사하십시오. 아래 형식을 정확히 따르십시오.

# 요약 점수표

| 평가 항목 | 점수 |
|-----------|------|
| **최종 결정 (Final Decision)** | **[Desk Reject / Major Reject / Minor Reject / Borderline / Weak Accept / Accept / Strong Accept]** |
| **최종 점수 (Final Score)** | **[X]** / 10 |
| 신규성 (Novelty) | [X] / 10 |
| 기술 완성도 (Technical Quality) | [X] / 10 |
| 실험 품질 (Experimental Quality) | [X] / 10 |
| 작성 품질 (Writing Quality) | [X] / 10 |
| 중요도 (Significance) | [X] / 10 |

# 1. 핵심 강점 (Strengths)
당신의 전문 관점에서 본 주요 강점 3가지를 구체적으로 설명하십시오.

# 2. 핵심 약점 (Weaknesses)
당신의 전문 관점에서 본 주요 약점 3가지를 구체적으로 설명하십시오.

# 3. 세부 전문 평가
당신의 전문 영역 관점에서 논문을 상세히 평가하십시오. (400-600자)

# 4. 저자에게 보내는 핵심 질문 (3가지)
반드시 답변이 필요한 질문 3가지를 작성하십시오.

# 5. 최종 의견
최종 결정의 이유를 2-3문장으로 명확히 요약하십시오.
"""

# ── 메타 리뷰어 프롬프트 빌더 ────────────────────────────────────
def build_meta_prompt(reviewer_texts: dict, venue_name: str) -> str:
    return f"""아래는 **{venue_name}**에 제출된 논문에 대한 3명의 리뷰어 의견입니다.

---

## 검토자 1 (기술 전문가 · MIT/CMU):
{reviewer_texts.get(1, '(리뷰 없음)')}

---

## 검토자 2 (신규성/영향력 전문가 · Google/FAIR):
{reviewer_texts.get(2, '(리뷰 없음)')}

---

## 검토자 3 (보수적 학자 · KAIST/서울대):
{reviewer_texts.get(3, '(리뷰 없음)')}

---

위 3개 리뷰를 종합하여 Area Chair로서 최종 결정을 내리십시오. 아래 형식을 정확히 따르십시오.

# 최종 심사 결과 요약

| 항목 | 검토자 1 | 검토자 2 | 검토자 3 | **최종 합의** |
|------|---------|---------|---------|------------|
| **최종 결정** | [결정1] | [결정2] | [결정3] | **[최종결정]** |
| **최종 점수** | [X]/10 | [X]/10 | [X]/10 | **[X]/10** |
| 신규성 | [X]/10 | [X]/10 | [X]/10 | [X]/10 |
| 기술 완성도 | [X]/10 | [X]/10 | [X]/10 | [X]/10 |
| 실험 품질 | [X]/10 | [X]/10 | [X]/10 | [X]/10 |
| 작성 품질 | [X]/10 | [X]/10 | [X]/10 | [X]/10 |
| 중요도 | [X]/10 | [X]/10 | [X]/10 | [X]/10 |

**한 줄 요약:** [이 논문에 대한 Area Chair의 전반적 인상을 1문장으로]

---

# 리뷰어 합의 사항
3명이 공통적으로 동의하는 주요 강점과 약점을 정리하십시오.

# 리뷰어 불일치 사항
의견이 갈리는 부분과 Area Chair로서의 판단을 설명하십시오.

# 최종 결정 및 근거
**최종 결정: [Desk Reject / Major Reject / Minor Reject / Borderline / Weak Accept / Accept / Strong Accept]**
최종 결정의 이유를 상세히 설명하십시오.

# 저자에게 전달할 필수 수정 사항
가장 중요한 수정 사항 3-5가지를 구체적으로 나열하십시오.

# 적합한 제출 대상 추천

현재 논문의 완성도를 기준으로 가장 적합한 제출 대상을 아래 형식으로 작성하십시오.

**현재 상태로 바로 제출 가능한 곳:**
[현재 수준에서 합격 가능성이 있는 컨퍼런스/저널을 구체적으로 명시. 없으면 "없음 - 대폭 수정 필요"로 표기]

**수정 후 목표할 수 있는 곳:**
[제안한 수정 사항을 반영하면 도전 가능한 컨퍼런스/저널을 구체적으로 명시]

**최종 목표로 삼을 수 있는 곳 (장기적):**
[연구 방향이 발전할 경우 최종적으로 노릴 수 있는 최고 수준 venue]

**제출 전략 한 줄 조언:**
[저자에게 전달하는 핵심 전략 조언 1문장]
"""


def safe_str(text: str) -> str:
    return text.encode("utf-8", errors="replace").decode("utf-8")


def extract_text_from_pdf(file_bytes: bytes) -> str:
    text_parts = []
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text_parts.append(safe_str(t))
    return "\n".join(text_parts)


def extract_text_from_docx(file_bytes: bytes) -> str:
    doc = Document(io.BytesIO(file_bytes))
    return "\n".join(safe_str(p.text) for p in doc.paragraphs if p.text.strip())


async def fetch_venue_info(url: str) -> str:
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            text = soup.get_text(separator=" ", strip=True)
            return re.sub(r"\s+", " ", text)[:5000]
    except Exception as e:
        return f"(URL 접근 실패: {e})"


FREE_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "openai/gpt-oss-20b:free",
    "openai/gpt-oss-120b:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "google/gemma-4-31b-it:free",
]


def run_reviewer(client, reviewer_id: int, system_prompt: str, user_prompt: str,
                 result_queue: q_module.Queue):
    """개별 리뷰어를 별도 스레드에서 실행, 결과를 queue에 넣음"""
    last_err = ""
    for model in FREE_MODELS:
        try:
            stream = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                max_tokens=2500,
                stream=True,
                extra_headers={"HTTP-Referer": "http://localhost:8000",
                               "X-Title": "Academic Paper Reviewer"},
            )
            for chunk in stream:
                text = chunk.choices[0].delta.content
                if text:
                    result_queue.put(("chunk", reviewer_id, safe_str(text)))
            result_queue.put(("done", reviewer_id, None))
            return
        except Exception as e:
            last_err = safe_str(str(e))
            if "401" in last_err or "invalid" in last_err.lower():
                result_queue.put(("error", reviewer_id, "API 키 오류"))
                return
            continue
    result_queue.put(("error", reviewer_id, f"모든 모델 한도 초과: {last_err[:120]}"))


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    with open("static/index.html", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


@app.post("/api/review")
async def review_paper(
    file: UploadFile = File(...),
    venue_name: str = Form(...),
    venue_url: Optional[str] = Form(None),
):
    # 파일 텍스트 추출
    file_bytes = await file.read()
    fname = (file.filename or "").lower()
    if fname.endswith(".pdf"):
        try:
            paper_text = extract_text_from_pdf(file_bytes)
        except Exception as e:
            raise HTTPException(400, f"PDF 파싱 오류: {e}")
    elif fname.endswith(".docx"):
        try:
            paper_text = extract_text_from_docx(file_bytes)
        except Exception as e:
            raise HTTPException(400, f"DOCX 파싱 오류: {e}")
    else:
        raise HTTPException(400, "PDF 또는 DOCX 파일만 지원합니다.")

    if not paper_text.strip():
        raise HTTPException(400, "텍스트를 추출할 수 없습니다. 스캔 PDF인 경우 텍스트 레이어가 필요합니다.")

    paper_text = paper_text[:25000]

    # 저널 URL 정보 수집
    venue_context = ""
    if venue_url and venue_url.strip():
        raw = await fetch_venue_info(venue_url.strip())
        venue_context = (f"\n**저널/컨퍼런스 정보 ({venue_url}):**\n{raw}\n\n"
                         "위 정보를 참고하여 해당 venue의 수준과 기준으로 평가하십시오.\n")

    # API 키 확인
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise HTTPException(500, "서버에 OPENROUTER_API_KEY가 설정되지 않았습니다.")

    or_client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=key)

    # 각 리뷰어용 사용자 프롬프트 (같은 템플릿, 다른 system prompt)
    user_prompt = REVIEWER_PROMPT_TEMPLATE.format(
        venue_name=venue_name,
        venue_context=venue_context,
        paper_text=paper_text.encode("utf-8", errors="replace").decode("utf-8"),
    )

    reviewer_systems = {
        1: REVIEWER_1_SYSTEM,
        2: REVIEWER_2_SYSTEM,
        3: REVIEWER_3_SYSTEM,
    }

    def generate():
        def sse(data: dict) -> bytes:
            return ("data: " + json.dumps(data, ensure_ascii=False) + "\n\n").encode("utf-8", errors="replace")

        result_queue = q_module.Queue()
        reviewer_texts = {1: "", 2: "", 3: ""}

        # 3개 리뷰어 병렬 스레드 시작
        threads = []
        for rid, sys_prompt in reviewer_systems.items():
            t = threading.Thread(
                target=run_reviewer,
                args=(or_client, rid, sys_prompt, user_prompt, result_queue),
                daemon=True,
            )
            threads.append(t)

        for t in threads:
            t.start()

        # 3개 리뷰어 결과 수집 (최대 5분 대기)
        done_count = 0
        while done_count < 3:
            try:
                event_type, rid, data = result_queue.get(timeout=300)
            except q_module.Empty:
                yield sse({"reviewer": "system", "error": "리뷰어 응답 시간 초과 (5분)"})
                break

            if event_type == "chunk":
                reviewer_texts[rid] += data
                yield sse({"reviewer": rid, "text": data})
            elif event_type == "done":
                done_count += 1
                yield sse({"reviewer": rid, "done": True})
            elif event_type == "error":
                done_count += 1
                yield sse({"reviewer": rid, "error": data})

        # 메타 리뷰어 실행
        yield sse({"reviewer": "meta", "status": "start"})
        meta_prompt = build_meta_prompt(reviewer_texts, venue_name)

        last_err = ""
        for model in FREE_MODELS:
            try:
                stream = or_client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": META_REVIEWER_SYSTEM},
                        {"role": "user",   "content": meta_prompt},
                    ],
                    max_tokens=3000,
                    stream=True,
                    extra_headers={"HTTP-Referer": "http://localhost:8000",
                                   "X-Title": "Academic Paper Reviewer"},
                )
                for chunk in stream:
                    text = chunk.choices[0].delta.content
                    if text:
                        yield sse({"reviewer": "meta", "text": safe_str(text)})
                yield sse({"reviewer": "meta", "done": True})
                yield b"data: [DONE]\n\n"
                return
            except Exception as e:
                last_err = safe_str(str(e))
                if "401" in last_err or "invalid" in last_err.lower():
                    yield sse({"reviewer": "meta", "error": "API 키 오류"})
                    yield b"data: [DONE]\n\n"
                    return
                continue

        yield sse({"reviewer": "meta", "error": f"메타 리뷰어 실패: {last_err[:120]}"})
        yield b"data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream; charset=utf-8",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
