# tossai 아키텍처 (박부장 작동 원리)

> 토스증권 Open API 기반 **분석 전용** 투자 AI. 12개 정량 전략으로 종목을 거르고,
> Claude가 거시·뉴스·실적까지 보고 한글로 매수/매도/보유를 판단해 슬랙으로 보냅니다.
> **주문은 절대 내지 않습니다(analysis-only).**

최종 업데이트: 2026-06 · 브랜치 `claude/toss-securities-investment-ai-0lus7s`

---

## 1. 한눈에 보는 흐름

```
[유니버스 45종목]
      │  토스 API: 캔들(OHLCV) 수집 (200봉 초과는 before 커서로 페이징)
      ▼
[① 스크리닝 — 12전략 앙상블]  정량·객관
      │  각 전략이 종목 평가 → 병합/중복제거(max score) → VIX 레짐 가중 → 점수순 top-N
      ▼
[② 시장 컨텍스트 수집]  뉴스·다음 실적일(yfinance) + 거시(FRED 지표 + FOMC 일정)
      ▼
[③ Claude 최종 판단]  정성 — 종목당 1회, forced tool-use
      │  숫자 시그널 + 컨텍스트 → BUY/HOLD/SELL · 확신도 · 핵심 · 리스크 (한글)
      ▼
[④ 리스크패리티 비중 제안]  역변동성 (제안일 뿐 주문 아님)
      ▼
[⑤ 리포트 저장(JSON) + 알림]  콘솔 / 슬랙 / 웹훅 / 이메일
```

포트폴리오 모드는 ①·② 대신 **토스 보유종목 조회**로 시작해, 보유 각 종목에
평가손익 기반으로 ADD/HOLD/TRIM/SELL 조언을 냅니다.

---

## 2. 슬랙으로 나가는 메시지 (5종)

| 메시지 | 트리거 | 내용 |
|---|---|---|
| 📈 추천 시그널 | `run-once`(cron 장중) / `/recommend` | 워치리스트에서 거른 매수/매도 후보 + 근거 |
| 💼 보유 포트폴리오 조언 | `portfolio`(cron/수동) | 실제 보유 종목 ADD/HOLD/TRIM/SELL + 평가손익 |
| 🌅 모닝 브리핑 | 매일 장 시작 전(스케줄) | 오늘의 관심종목 + VIX 시장국면 |
| 🗓️ 주간 브리핑 | 매주(스케줄) | 한 주 시그널 집계·평균 확신도 |
| 🚨 리스크 경보 | 15분마다 스캔 | VIX 급등(블랙스완)·갭다운 발생 시 |

**종목 카드 구성** (블록): 제목(종목명+티커+액션) · 메타 context(확신도 막대 ▰▰▱,
손익 🔺🔻, 🎯목표가/현재가, ✅전략 동의 수, 🌐거시 한 줄) · *핵심* 불릿 · *리스크* ⚠️ · 면책.
긴 본문은 잘리지 않고 여러 섹션/메시지로 분할 전송. Claude 마크다운은 Slack mrkdwn으로 변환.

---

## 3. 전략 앙상블 (12개)

판단은 **하이브리드**: 규칙 기반 12전략이 후보를 거르고(정량), Claude가 종합 판단(정성)을 얹음.
여러 전략이 같은 종목을 집으면 `flagged_by`로 합의 표시(예: "4개 전략 동의").
VIX 위험국면이면 공격적(long) 전략 점수를 `regime_riskoff_weight`만큼 down-weight.

### 가격/기술 전략 (8)
| 전략 | 핵심 로직 | bucket |
|---|---|---|
| `technical_swing` | 기존 스크리너(RSI·SMA·거래량 서지) 래핑 | swing |
| `dual_momentum` | Antonacci: 상대모멘텀(252일 수익률) + 절대모멘텀 게이트 + MA200 추세 | long |
| `canslim` | CAN SLIM 기술 서브셋: 52주 신고가 근접·RS·거래량·MA50>MA200·VIX 게이트 | swing |
| `mean_reversion` | 상승추세(>MA200) 내 과매도(RSI<35) + 레인지 하단 | swing |
| `trend_breakout` | Donchian/52주 신고가 돌파 + 거래량 확인 + MA200 위 | long |
| `meb_faber` | GTAA 10개월(≈200일) SMA 타이밍 | long |
| `momentum_quality` | 12-1 모멘텀 + FIP(frog-in-the-pan) 매끄러움 가중 | long |
| `low_volatility` | 저변동성 이상현상(MA200 위 종목만) | long |

### 펀더멘털 대가 전략 (4) — pykrx(KRX)/yfinance(US), lazy + graceful degrade
| 전략 | 핵심 로직 | bucket |
|---|---|---|
| `graham` | PER≤15 ∧ PBR≤1.5 ∧ PER·PBR≤22.5 ∧ 그레이엄수≥가격 | value |
| `magic_formula` | 그린블랫: earnings yield + ROC 교차 랭킹 | value |
| `buffett_quality` | ROE≥15% ∧ 적정 PER ∧ 품질·가치 결합 | value |
| `piotroski` | F-Score(무료소스로 가능한 항목 베스트에포트) | value |

전략 추가/교체는 `screening/strategies/ensemble.py`의 `REGISTRY` + `build_strategy()`로.
기본 활성 목록은 `config.py`의 `strategy` 콤마 리스트.

---

## 4. 시장 컨텍스트 레이어 (거시·뉴스·실적)

`src/tossai/context/` — fundamentals와 동일하게 lazy-import + fail-soft + 1회 캐시.
**정성적 참고용**으로 Claude에 전달(수치 판단이 우선; 임박한 실적/FOMC는 타이밍 리스크로 표시).

- **종목 뉴스 헤드라인** — yfinance `Ticker.news` (기본 3개, US는 잘 붙고 KRX는 편차)
- **다음 실적일** — yfinance `Ticker.calendar`
- **거시 지표** — FRED API: 실업률·기준금리·10년물·CPI(YoY) (`FRED_API_KEY` 있을 때만)
- **FOMC 일정** — 2026 일정 내장(키 불필요), 다음 회의까지 D-day 표시

`MarketContextProvider.payload_for(symbol, market)` → Claude payload의 `market_context`.
슬랙 헤더엔 `🌐 실업률 4.0% · CPI(YoY) +3.1% · FOMC D-2` 한 줄로 표시.

---

## 5. Claude 분석 엔진

`src/tossai/analysis/` — **forced tool-use**로 항상 파싱 가능한 구조화 출력.
- 추천: `submit_recommendation` (action BUY/HOLD/SELL, confidence, target_price, rationale,
  key_points, risks, time_horizon)
- 포트폴리오: `submit_position_advice` (action ADD/HOLD/TRIM/SELL, …)
- **출력 규칙**: rationale은 한 줄 요약, 본문은 짧은 `key_points` 불릿, 전부 **한국어 강제**
  (시스템 프롬프트 + 툴 스키마 필드 설명 + 유저 메시지 3중 강제).
- 모델: 기본 `claude-sonnet-4-6`, `--deep`이면 `claude-opus-4-8`. 토큰 누적 비용 가드.

---

## 6. 백테스트 + 리스크 관리

`src/tossai/backtest/` — 워크포워드(룩어헤드 없음), 거래비용(턴오버 기반), 성과지표.
- 리밸런스마다 재스크리닝 → top-N 보유 → k→k+1 수익 적용
- **리스크 관리(실측 튜닝)**: 분산(top-10) + **추세 익스포저 필터(MA100)** 가 핵심.
  보유 종목이 자기 MA(기본 100일) 이탈 시 그 비중을 현금화 → 낙폭 축소.
  (역변동성 가중·변동성 타깃은 이 전략에선 수익만 깎아 기본 OFF.)
- **섹터 분산 캡**(`max_per_sector`, 기본 OFF): 같은 섹터 보유 수 상한. 기능은 있으나
  **실측상 낙폭을 못 줄였음** — 이 전략의 낙폭은 섹터 집중이 아니라 모멘텀 팩터 드로다운
  (고베타 종목이 섹터 무관하게 동반 하락)이기 때문. 추천 다양성용으로만 옵션 유지.
- 실측: 낙폭 **-38.9% → -25.4%**, Sharpe 1.65 → 1.72, CAGR ~62% (매수후보유 44%, 낙폭 -13%).
  → 고수익·고위험 지점. 낙폭을 더 낮추려면 유니버스 확장/섹터 분산 필요(미구현).

명령: `python -m tossai backtest --years 3 [--top N] [--trend-ma 100] [--vol-target 0.2]`

### 추천 성과 추적 (`performance/`)
`run-once`가 매번 추천을 `reports/recommendations.jsonl` 원장에 기록 → `track` 명령이
이후 가격으로 **방향조정 전방수익**(BUY=+수익, SELL=−수익)을 채점. 적중률·평균수익을
기간별(5/21/63일)·액션별로 집계하고, **확신도가 실제로 유의미한지**(≥0.7 vs <0.7) 비교.
기존 저장 리포트에서 자동 백필. 외부 데이터 불필요(이미 받는 캔들 사용).
명령: `python -m tossai track [--horizons 5,21,63] [--min-confidence 0.6]`

---

## 7. 패키지 구조

```
src/tossai/
├── cli.py            명령어: doctor / screen-only / run-once / run-loop / portfolio / backtest / serve
├── config.py         pydantic-settings (.env). 비밀은 redacted_summary로만 로깅
├── models.py         Candidate / Position / Recommendation / PositionAdvice / DISCLAIMER
├── toss/             토스 API: auth(OAuth) · client(캔들/계좌/보유, 페이징·429 백오프) · schemas
├── screening/        indicators · strategies/(12종+ensemble+regime) · allocation(역변동성)
├── fundamentals/     pykrx/yfinance 재무 provider (lazy, fail-soft)
├── context/          거시·뉴스·실적 provider (lazy, fail-soft)
├── analysis/         claude_engine · prompts · portfolio_prompts
├── portfolio/        analyzer (보유종목 분석)
├── performance/      추천 성과 추적: ledger(원장) · tracker(전방수익 채점)
├── backtest/         engine(워크포워드+리스크관리) · metrics
├── risk/             sentiment(VIX) · evaluators(블랙스완/갭다운) · models
├── output/           report · portfolio_report · alerts(콘솔/슬랙/웹훅/메일)
├── slack/            blocks(Block Kit) · server(FastAPI 슬래시) · web_client · commands · signature
├── scheduler/        jobs(브리핑·리스크 정기) · briefings
├── market/           universe · calendar
└── pipeline/         orchestrator (전체 조립)
```

배포: EC2에서 `tossai.timer`(정기 분석) + `tossai-serve`(슬랙 인터랙티브). `deploy/` 참고.

---

## 8. 안전장치 — 분석 전용 (절대 주문 없음)

- `orders.py`는 **비활성 스텁**.
- `ENABLE_TRADING=true`면 `enforce_safety()`가 **시작 거부**.
- slack/scheduler/risk/portfolio/screening 패키지가 주문 코드를 **import조차 못 하도록
  AST 테스트(`tests/test_safety.py`)로 강제**.
- 모든 메시지·리포트 하단에 면책 문구(`DISCLAIMER`).
- 라이브 토스 자격증명은 **저장소에 절대 커밋/로깅 금지** — EC2 `.env`에만.

---

## 9. 한계 / 알아둘 점

- 백테스트상 낙폭(-25%)이 매수후보유(-13%)보다 큼 → **판단 보조일 뿐, 분산 책임은 사용자**.
- 뉴스/실적은 yfinance라 **US는 잘 붙고 KRX는 데이터가 적음**(없으면 자동 생략).
- 거시 지표 값은 `FRED_API_KEY` 필요(없으면 FOMC 일정만).
- VIX는 백테스트에서 단일 스냅샷(과거 구간 방어엔 기여 못 함).
- 스크리닝 통과 종목이 ~10개로 제한적(유니버스 45종목·모멘텀 군집).

개선 후보는 `docs/CODE_REVIEW.md` 참고.
