# tossai 코드 리뷰 & 갭 분석

작성: 2026-06 · 대상 브랜치 `claude/toss-securities-investment-ai-0lus7s`

> **CODEX CLI 메모**: codex CLI는 설치했으나 이 실행 환경의 네트워크 정책이
> `api.openai.com`을 차단(egress 허용목록)해 여기서는 실행 불가였습니다.
> EC2(인증·네트워크 가능 시)에서는 아래로 돌릴 수 있습니다:
> ```bash
> cd ~/tossai && codex review --base main
> ```
> 본 문서는 내부 리뷰(Claude 감사 에이전트, 코드 정독 기반)로 작성했습니다.
> 효과 추정 수치(bps)는 검증 불가라 의도적으로 제외하고 **우선순위로만** 표기합니다.

전체 결론: **보안·안전 보증은 견고하고, 구조는 건전.** 치명적 버그는 없으며,
개선 포인트는 (1) 일부 견고성 보강, (2) 전략/지표 추가, (3) 성과 추적 기능입니다.

---

## A. 정확성 (Correctness)

| 항목 | 위치 | 판정 |
|---|---|---|
| 백테스트 룩어헤드 | `backtest/engine.py` k→k+1 루프 | ✅ 문제 없음 (k까지만 학습, k→k+1 수익). 명시적 룩어헤드 테스트 추가 권장 |
| 추세 MA 윈도잉 | `backtest/engine.py` `_ma_series` | ✅ 길이 일치·경계 가드됨. `len==len` 단위테스트 추가 권장 |
| 변동성 타깃 자기참조 | `backtest/engine.py` 변동성 스케일 | ✅ 과거 변동성만 사용(룩어헤드 없음). 1-bar stale는 설계상 정상 |
| 돌파 전략 shift(1) | `trend_breakout.py` | ✅ 당일 제외(`shift(1)`) 정확 |
| 지표 0除 / NaN | `indicators.py` rsi·volume_ratio·range_position | ✅ `replace(0, nan)`로 가드됨 |

→ **실제 정확성 버그 없음.** 보강은 "테스트로 못박기" 수준.

---

## B. 견고성 / 에러 처리 (실제 개선 여지 O)

| 심각도 | 항목 | 위치 | 권장 수정 |
|---|---|---|---|
| **중** | `analyze_position`에 재시도 없음 | `analysis/claude_engine.py` (`_call`엔 @retry 있으나 `analyze_position`은 `messages.create` 직접 호출) | Anthropic 호출을 공용 재시도 메서드로 추출해 양쪽 재사용 |
| **중** | 토스 종목 간 레이트리밋 미적용 | `toss/client.py` (페이지 사이 `sleep(0.25)`만, 종목 사이엔 없음) | 전역 레이트 게이트(세마포어/최소 간격)로 다수 종목 스크리닝 시 429 방지 |
| **중** | FRED 실패가 조용히 빈 dict | `context/sources.py` `fetch_macro`/`_fred_obs` | 첫 실패는 WARNING 로깅, `doctor`에 FRED 키 점검 추가 |
| 하 | yfinance `_quiet()`가 예외도 가림 | `context/sources.py` `_quiet` | 예외 시 1회는 WARNING으로 표면화 |
| 하 | 토스 페이징 중 손상 bar 무시 | `toss/client.py` 캔들 파싱 | 손상 비율 임계 초과 시 경고 |
| 하 | Slack `respond`/SMTP 재시도 없음 | `slack/web_client.py`, `output/alerts.py` | tenacity 재시도 추가 |

---

## C. 보안 / 안전 — ✅ 전부 통과

- **주문 차단**: `orders.py` 스텁 + `enforce_safety()`(ENABLE_TRADING 거부) +
  `tests/test_safety.py` AST 검사(slack/scheduler/risk/portfolio/screening가 orders import 금지). **견고.**
- **비밀 비노출**: `config.redacted_summary()`는 `*_set` 불리언만 반환. 토큰·키 원문 로깅 없음.
- **Slack 토큰**: WebClient 내부 보관, 직렬화/로깅 없음.
- 경미: 비어있는 `ANTHROPIC_API_KEY`는 `doctor`에서만 검증 → 다른 명령에서도 부팅 시 점검 권장.

---

## D. 테스트 커버리지 갭

직접 테스트가 없는(간접만) 모듈: `market/calendar.py`, `market/universe.py`,
`logging_setup.py`, `cli.py`(통합). 추가 권장 케이스:
- `_fred_yoy` 경계(분모 0)
- 변동성 타깃 `recent_rets < lookback`
- Slack 50블록 초과 분할 전송(`web_client` 배칭)
- 오케스트레이터: 후보 0개일 때 다운스트림 무사
- 시장 캘린더 비거래일

(현재 167개 테스트 통과 — 외부 소스 전부 모킹.)

---

## E. 전략 / 지표 갭 (가장 중요) — 우선순위순

현재 12전략(기술 8 + 펀더멘털 4)은 **모멘텀·추세·가치·품질**을 잘 덮지만, 다음이 비어 있습니다.

### 빠른 효과 (낮은 난이도)
1. ~~**섹터 분산 캡**~~ — ✅ **구현됨**(`max_per_sector`, 기본 3). `universe.yaml`의 `sector:`
   라벨 기반으로 같은 섹터 보유 수 상한. 백테스트 `--max-per-sector`로 효과 측정 가능.
   *현재 최대 약점인 "모멘텀 군집 동반 폭락(낙폭)"의 직접 해법.*
2. **ATR 기반 포지션 한도/스톱** — 보유당 ATR 배수로 손절·사이징 → 꼬리 손실 축소.
3. **종목별 최대 비중 캡** — 앙상블이 핫한 한 종목에 과집중하지 않도록 10~15% 하드캡.

### 중간 난이도 (알파 기여 큼)
4. **벤치마크 상대강도(RS vs KOSPI/SPX)** — 절대모멘텀에 더해 지수 대비 랭킹을 top-N 정렬에 반영.
5. **실적 추정치 상향(Estimate Revision)** — 최근 90일 EPS 추정 상향 종목 가점(yfinance).
6. **이익의 질(Accruals)** — 발생액 높은(현금흐름 대비 이익 과대) 종목 감점 → 가치 함정 회피.
7. **변동성 레짐(VIX 외)** — 롤링 변동성 백분위/GARCH로 국면 분류해 사이징 조절(현재 VIX 정적 임계만).

### 고난이도 (선택)
8. **마켓 베타 헤지/팩터 중립** — 저베타 매수·고베타 매도로 시장방향 중립(롱온리 한계 보완).
9. 페어/통계적 차익, 옵션 IV 스큐 — 데이터·복잡도 대비 한계효용 낮음(후순위).

### 운영 측면
10. **US 보유 환(FX) 인지** — KRW/USD 변동을 평가손익·리스크 노트에 반영(헤지 제안만).

> **추천 우선순위(MVP 3종)**: ① 섹터 분산 캡, ② ATR 스톱/사이징, ③ 지수 상대강도.
> 셋 다 백테스트 최대 약점(낙폭·집중)을 직접 겨냥.

---

## F. 기능 / 제품 갭 — 우선순위순

1. **과거 추천 성과 추적** *(최고 가치)* — 각 알림의 진입가·이후 수익/적중률을 기록해
   "박부장 추천의 실제 알파"를 월별 집계. 측정 없으면 개선도 없음.
2. **포지션별 스톱 경보** — 보유가 진입가 대비 −X% 또는 −2×ATR 이탈 시 경고(매수가 추적 필요).
3. **포트폴리오 조언 백테스트** — 과거 보유 조언을 실제 가격에 리플레이해 사후 검증(`--backtest-portfolio`).
4. **웹 대시보드** — 후보·보유·누적 성과 곡선을 한 화면에(Slack 보완).
5. **멀티 계좌** — `toss_account_seq` 리스트화, 계좌별 보유 그룹·조언.
6. **알림 dedup/이력** — 동일 종목 반복 알림 억제 + 알림 이력 저장.
7. **유니버스 핫리로드** — `universe.yaml` 재시작 없이 갱신.
8. **세금 lot 인지** — 매도 lot(FIFO/최적 원가) 추적(토스 API 노출 여부 확인 필요).

---

## 다음 액션 제안 (스프린트)

- **즉시(저위험)**: `analyze_position` 재시도 추가 · `_fred_yoy` 경계 테스트 · 룩어헤드 명시 테스트.
- **단기**: 섹터 분산 캡 + 종목 최대비중 캡(백테스트 낙폭 직접 개선) · 과거 추천 성과 추적.
- **중기**: 지수 상대강도 · ATR 스톱 경보 · 웹 대시보드.

어떤 항목을 먼저 구현할지 골라주시면 거기부터 진행하겠습니다.
