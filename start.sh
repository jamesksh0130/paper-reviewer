#!/bin/bash
cd "$(dirname "$0")"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8
echo "📄 Academic Paper Reviewer 시작 중..."
echo "→ http://localhost:8000 에서 접속 가능"
echo "Ctrl+C 로 종료"
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
