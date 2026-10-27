# 협업 규칙 (CONTRIBUTING)

이 레포는 **PR 기반**으로 운영한다. `main` 직접 push 는 막혀 있고, 모든 변경은
브랜치 → Pull Request → **총합 관리자(@zeldaim) 리뷰·머지**로만 반영된다.

## 작업 흐름

```bash
# 1. 최신 main 받기
git checkout main && git pull

# 2. 작업 브랜치 생성 (main 에서 바로 작업 금지)
git checkout -b feat/내작업            # 기능: feat/, 버그: fix/, 문서: docs/, 실험: exp/

# 3. 작업 후 브랜치 push (main 아님!)
git add -A && git commit -m "feat: 무엇을 했는지"
git push -u origin feat/내작업

# 4. GitHub 에서 Pull Request 생성 → 관리자가 리뷰·머지
```

## 브랜치 이름 규칙
- `feat/<이름>` 기능 · `fix/<이름>` 버그 · `docs/<이름>` 문서 · `exp/<이름>` 실험

## 커밋 메시지
- 접두어 + 한 줄 요약: `feat:`, `fix:`, `docs:`, `exp:`, `chore:`
- 예: `feat(ml): RF 세션분할 학습 스크립트 추가`

## 커밋하면 안 되는 것 (`.gitignore` 확인)
- VM 디스크·이미지 (`.vmdk`, `.vmx`, `.iso`)
- 100MB 이상 원천 로그 — `ml/data/raw_logs/` 는 샘플만, 대용량은 제외
- 학습 모델 가중치(`.joblib`, `.pkl`)가 크면 Releases/LFS 로
- **비밀번호·자격증명·실제 토큰·운영 IP** (README 처럼 공유해야 하면 마스킹)

## 디렉터리 소유
`.github/CODEOWNERS` 참고 — 경로별 담당자가 PR 에 자동 리뷰어로 붙는다.

## 새 장애/설정 변경
`docs/troubleshooting/` 에 `03_...`, `04_...` 형태로 문서 추가하고 README 표를 갱신한다.
