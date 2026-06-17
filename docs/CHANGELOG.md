# 변경 이력 (Changelog)

작업 브랜치: `claude/toss-securities-investment-ai-0lus7s`
모든 기능은 **분석 전용**(주문 미실행) 원칙을 유지합니다.

---

## 2026-06-17 — 성과추적·대화형 에이전트·시장심리 지표

### 새 기능
- **포트폴리오 조언 백테스트** (`track --portfolio`)
  - 과거 보유 조언(ADD/HOLD/TRIM/SELL)을 이후 가격으로 사후 채점.
  - ADD=강세, TRIM/SELL=약세, HOLD=중립(제외). `portfolio_*.json`에서 자동 백필.
  - `performance/`의 추천 채점기를 재사용(방향 매핑 확장 + 액션별 통계 동적화).

- **박부장 — 대화형 AI 투자부장** (`agent/`)
  - Claude tool-use 에이전트. 읽기전용 도구로 내 데이터를 직접 조회해 한글로 답함.
  - 도구: `read_portfolio` · `read_recommendations` · `performance` · `quote` ·
    `market_overview`(VIX·거시·공포탐욕·FOMC) · `news`(종목 헤드라인).
  - CLI `ask`(단발/REPL) + Slack `/박부장`(별칭 `/ask`). Slack은 (채널,사용자)별 대화 메모리로
    연속 질문 맥락 유지(serve 프로세스 수명 동안, 1시간/최근 12턴).

- **일일 자동 적재** (`daily`) + 모닝 브리핑 cron 발송 (`briefing`)
  - `daily`: 보유종목 조언 갱신 + 두 원장(추천/조언) 성과 스냅샷. serve 없이 cron만으로 누적.
  - `briefing`: 모닝/주간 브리핑을 serve 없이 cron으로 Slack 발송. `alerts.post_to_slack()` 헬퍼.

### 개선
- **모닝 브리핑 강화** — 거시 한 줄(🌐) + 보유 포트폴리오 요약(가치가중 손익 + 종목별 최신 조언 태그)
  추가. 계좌/매크로 미설정 시 해당 섹션 자동 생략(fail-soft).
- **시장 심리·레짐 지표 보강** — VIX 외에 3종 추가, 🌐 브리핑 줄 + Claude 컨텍스트에 투입:
  - CNN **공포·탐욕 지수**(0–100, 무키)
  - **10Y-2Y 금리차**(FRED `T10Y2Y`, 역전=침체 경고)
  - **하이일드 신용 스프레드**(FRED `BAMLH0A0HYM2`, 위험선호)
- **Claude 호출 견고성** — 추천/포트폴리오 분석 모두 공유 `_create()`로 통일, 일시적 5xx
  (`InternalServerError`)까지 재시도. 일시 장애로 종목 누락되던 문제 해소.
- **FRED 견고성** — 시리즈별 독립 실패 처리(한 지표 실패가 나머지를 막지 않음),
  CPI YoY는 당월 미발표(`.`) 행을 흡수하도록 14개 관측치 요청.
- **박부장 시장·뉴스 도구** — `market_overview`(VIX+밴드·FRED 거시·공포탐욕·다음 FOMC),
  `news`(yfinance 종목 헤드라인) 추가. "오늘 증시 어때?"·"○○ 무슨 이슈 있어?"에 응답.
  모닝 브리핑이 쓰던 fail-soft 소스를 그대로 재사용(새 의존성 없음).
- **Slack 마크다운 렌더링 수정** — `advisor_blocks`가 `_slack_mrkdwn`를 거치지 않아 박부장
  답변의 `**굵게**`가 별표 문자로 노출되던 문제 수정. 긴 답변은 `_text_sections`로 자동 분할
  (truncation 제거).
- **문서** — `.env.example`에 시장 컨텍스트 섹션 추가(`FRED_API_KEY` 발급 링크 포함).
  `deploy/DEPLOY.md`에 daily 타이머·홈 디렉터리 cron·박부장·브리핑 절 추가.
  박부장 사용법·질문 카탈로그 문서 추가(`docs/ADVISOR.md`).

### 배포 메모
- EC2 타임존이 `Asia/Seoul`이라 cron은 KST로 해석됨.
- 홈 디렉터리(`~/tossai`) 배포는 systemd(`/opt/tossai` 가정) 대신 cron 사용.
  앱이 cwd의 `.env`를 자동 로드하므로 `EnvironmentFile` 불필요.
- 권장 평일 cron: run-once ×N(추천) · `briefing`(08:00) · `daily --slack`(06:30, 미 장마감 후).
- `FRED_API_KEY` 없으면 공포·탐욕/FOMC만 표시되고 FRED 거시 지표는 생략됨.

### 검증
- 테스트 211개 통과, ruff 클린. 주요 신규 기능은 EC2 실측으로 확인:
  박부장 대화, daily/briefing Slack 발송, 공포·탐욕 라이브, FRED 풀 거시 라인.
