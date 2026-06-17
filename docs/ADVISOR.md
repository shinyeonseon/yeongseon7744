# 박부장 — 대화형 투자부장 (`/박부장`)

`src/tossai/agent/advisor.py`. 한국 증권사 베테랑 투자부장 페르소나의 Claude tool-use
에이전트. **추측 대신 도구로 사용자의 실제 데이터를 조회한 뒤** 근거를 들어 한국어로
간결·직설적으로 답한다. 항상 리스크를 함께 짚으며, **분석·의견만 제공 — 주문은 절대
실행하지 않는다.**

Slack에서 `/박부장 <질문>` 으로 호출. 응답은 3초 내 ack 후 백그라운드 처리되어
`response_url`로 전송된다. 대화는 채널·사용자별로 **최근 12턴 / 1시간** 기억한다
(`ConversationStore`, serve 프로세스 생존 동안).

## 도구 (read-only, `src/tossai/agent/tools.py`)

| 도구 | 하는 일 | 데이터 출처 |
|------|---------|-------------|
| `read_portfolio` | 실제 보유 종목 + 손익 + 최신 ADD/HOLD/TRIM/SELL 조언 | `reports/portfolio_*.json` |
| `read_recommendations` | 워치리스트 최신 매수 후보 + 액션·확신도·근거 | `reports/*.json` |
| `performance` | 과거 추천/조언의 사후 성과(적중률·평균수익) | performance ledger |
| `quote` | 한 종목 현재가 + 1/5/20일 등락률 | 토스 캔들 |
| `market_overview` | VIX+밴드, 거시지표(FRED), 공포·탐욕, 다음 FOMC | `context/sources.py`, `risk/sentiment.py` |
| `news` | 종목별 최근 헤드라인(최대 5건) | yfinance |

`market_overview`의 FRED 거시지표(실업률·기준금리·미10년물·CPI·금리차·HY스프레드)는
`FRED_API_KEY`가 있을 때 채워진다. 키가 없어도 VIX·공포탐욕·FOMC는 동작한다.

## 물어볼 수 있는 질문 예시

### 💼 내 보유 종목 — `read_portfolio`
- "내 포트폴리오 어때?"
- "삼성전자 들고 있는데 어떡할까?"
- "지금 손실 나는 종목 뭐야?"
- "비중 줄여야 할 거 있어?"

### 🎯 매수 후보 / 추천 — `read_recommendations`
- "오늘 살 만한 거 있어?"
- "추천 종목 뭐야?"
- "확신도 높은 후보만 추려줘"

### 📊 시장 현황·분위기 — `market_overview`
- "오늘 증시 분위기 어때?"
- "지금 시장 위험해?"
- "공포·탐욕 지수 몇이야?"
- "다음 FOMC 언제야?"
- "금리 상황 어때?"

### 📰 종목 뉴스·이슈 — `news`
- "엔비디아 무슨 이슈 있어?"
- "테슬라 요즘 뉴스 뭐 있어?"
- "내 보유 종목 중에 악재 있는 거 있어?"

### 📈 개별 종목 시세 — `quote`
- "엔비디아 지금 얼마야?"
- "테슬라 최근 한 달 어때?"
- "애플 1주일 등락률은?"

### 🏆 추천 성적 — `performance`
- "네 추천 잘 맞아?"
- "지난 추천들 적중률 어때?"
- "내 포트폴리오 조언 성과 보여줘"

### 🔗 조합 질문 (한 답변에 여러 도구)
- "내 포트폴리오 보고 지금 시장 상황이랑 같이 판단해줘" → `read_portfolio` + `market_overview`
- "엔비디아 시세랑 뉴스 같이 보고 사도 될지 말해줘" → `quote` + `news`
- "오늘 시장 분위기 안 좋으면 내 종목 중 뭐 줄여야 해?" → `market_overview` + `read_portfolio`

### 🧠 이어서 대화 (기억함)
- "아까 그 종목 더 자세히 설명해줘"
- "그럼 그거 대신 뭘 사는 게 나아?"

## 한계 (의도된 설계)
- ❌ **매매 주문 실행/대행 안 함** — 분석·조언만.
- ❌ 데이터가 없으면 지어내지 않고, 무엇을 실행하면 채워지는지 안내(`run-once`/`portfolio`).
- ⚠️ `performance`·`quote`는 데이터가 며칠 쌓여야 의미 있는 결과가 나온다.

## 확장 방법
도구 추가는 `agent/tools.py`에 (1) `ADVISOR_TOOLS` 스키마, (2) `run_tool` 디스패치,
(3) 구현 함수를 더하고, 필요하면 `advisor.py`의 `PERSONA`에 사용 안내를 넣으면 된다.
모든 도구는 read-only를 유지한다 (주문/상태 변경 금지).
