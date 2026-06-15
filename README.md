# tossai — 토스증권 투자 AI (analysis-only)

토스증권 **Open API**로 시세를 가져와, **규칙 기반 기술적 스크리닝**으로 후보를 좁힌 뒤
**Claude(Anthropic API)**가 최종 매매 의견을 구조화해 산출하는 하이브리드 투자 AI입니다.
AWS EC2에서 주기적으로 실행하도록 설계되었습니다.

> ⚠️ **이 도구는 실제 주문을 내지 않습니다 (analysis-only).** BUY/HOLD/SELL "추천"과
> 근거·신뢰도·목표가를 리포트/알림으로 생성할 뿐입니다. 자동 매매가 아니며, 출력은
> 투자 자문이 아닙니다. 투자 책임은 본인에게 있습니다.

## 동작 방식 (파이프라인)

```
워치리스트(YAML) → Toss 시세/캔들 조회 → 기술적 스크리닝(규칙 퍼널, 스코어)
        → 상위 N개만 Claude 분석(tool-use 구조화 출력) → JSON 리포트 + 콘솔/웹훅 알림
```

- **스크리닝 / 전략 앙상블**(`screening/`): 여러 퀀트 전략이 각자 후보를 내고, 심볼별로
  병합(중복 제거·시그널 합산·`flagged_by` 누적)한 뒤 상위 `CLAUDE_MAX_CANDIDATES`개만 Claude로
  전달 → **비용 상한 결정적**. 투자 대가 전략들의 방법론을 참고해 재구현(코드 복사 X).

  **가격기반 전략**(토스 캔들+VIX만, 안정적):

  | 전략 | 버킷 | 요약 |
  |------|------|------|
  | `technical_swing` | swing | 추세·RSI·거래량·모멘텀 게이트(기존 룰 퍼널) |
  | `dual_momentum` | long | Antonacci 절대+상대 모멘텀(12개월 수익률) |
  | `canslim` | swing | CAN SLIM **기술적 서브셋**(52주 신고가·RS·거래량·MA·VIX 게이트) |
  | `mean_reversion` | swing | 상승추세 내 과매도 눌림목 |
  | `trend_breakout` | long | 52주 신고가 돌파 + 거래량 확인 |
  | `meb_faber` | long | 메브 파버 GTAA(10개월/200일 SMA 추세 타이밍) |
  | `momentum_quality` | long | 12-1 모멘텀 + FIP 추세 매끄러움(Wesley Gray) |
  | `low_volatility` | long | 저변동성 이상현상(상승추세 한정) |

  **펀더멘털 전략**(투자 대가 가치/품질 — 재무데이터 필요, 없으면 자동 skip):

  | 전략 | 버킷 | 요약 |
  |------|------|------|
  | `graham` | value | 벤저민 그레이엄 방어적 가치(저PER·저PBR·그레이엄수) |
  | `magic_formula` | value | 그린블랫 마법공식(이익수익률+ROC **교차 랭킹**) |
  | `buffett_quality` | value | 버핏 품질가치(고ROE+적정PER) |
  | `piotroski` | value | 피오트로스키 F-Score **부분(lite)** — 무료소스 한계 |

  펀더멘털 소스: **KRX=pykrx, US=yfinance** (lazy-import, `pip install -e ".[fundamentals]"`).
  미설치/네트워크 실패 시 해당 전략만 조용히 skip하고 가격기반 전략으로 계속 동작.

  **시장국면(regime) 필터**: VIX로 RISK_ON/NEUTRAL/RISK_OFF 분류 → RISK_OFF에선 long 버킷 가중치 하향.
  **리스크패리티 오버레이**(달리오 올웨더): 선별된 종목에 역변동성 **제안 비중**을 리포트에 첨부(주문 아님).
  `STRATEGY`(콤마 리스트)로 선택, `--strategy`로 1회 오버라이드.
- **분석**(`analysis/`): `submit_recommendation` 단일 tool을 `tool_choice`로 강제해
  항상 파싱 가능한 `{action, confidence, target_price, rationale, risks, time_horizon}` 산출.
- **안전**(`toss/orders.py`): 주문 모듈은 항상 예외를 던지는 비활성 스텁. 파이프라인에
  주문 경로 자체가 없고, `ENABLE_TRADING=true`면 시작을 거부합니다.

## 빠른 시작 (로컬)

```bash
# 1) 가상환경 + 설치
python3.11 -m venv .venv
./.venv/bin/pip install -e ".[dev]"

# 2) 설정
cp .env.example .env                       # TOSS_*, ANTHROPIC_API_KEY 채우기
cp config/universe.example.yaml config/universe.yaml

# 3) 점검 (주문 없음, 비용 거의 없음)
./.venv/bin/python -m tossai doctor

# 4) 무료 드라이런(스크리닝만, Claude 호출 없음)
./.venv/bin/python -m tossai screen-only

# 5) 전체 1회 실행 (장 마감 중엔 알림 억제, --force로 강제)
./.venv/bin/python -m tossai run-once --force
```

## 토스 Open API 키 발급

1. [corp.tossinvest.com/ko/open-api](https://corp.tossinvest.com/ko/open-api)에서 신청.
2. 발급된 **app key / app secret**을 `.env`의 `TOSS_APP_KEY`, `TOSS_APP_SECRET`에 입력.
3. 계좌 조회가 필요하면 `TOSS_ACCOUNT_SEQ`도 입력.

> 토스 Open API는 단계적 오픈 중이며, 일부 엔드포인트 경로·필드명은 라이브 문서에서
> 확정해야 합니다. 모든 토스 관련 스키마는 `src/tossai/toss/schemas.py`와
> `client.py` 한 곳에 `TODO(schema)` 마커로 격리되어 있어, 실제 응답에 맞춰
> 한 곳만 수정하면 됩니다. `doctor`로 조기 검증하세요.

## 명령어

| 명령 | 설명 |
|------|------|
| `doctor` | 설정·토큰·시세 1콜·Anthropic 키 점검 (주문 없음) |
| `screen-only` | 스크리닝만 (Claude 미호출, 무료) |
| `run-once [--force] [--deep]` | 전체 1회 실행 후 종료 (cron/systemd용) |
| `run-loop [--deep]` | 주기 반복, 장중에만 분석 |
| `serve` | **Slack 인터랙티브 서버 + 브리핑/리스크 스케줄러** (상주) |
| `backtest [--years --rebalance --top --weighting]` | 전략 앙상블 **워크포워드 백테스트** (Claude·주문 없음) |

`--deep`는 `CLAUDE_MODEL_DEEP`(기본 `claude-opus-4-8`)로 더 깊은 분석을 수행합니다.

**백테스트**: `python -m tossai backtest --years 3 --rebalance 21 --top 5`. 매 리밸런스일에
그 시점까지의 데이터로만 전략을 돌려(룩어헤드 없음) 상위 N종목을 보유, 일별 자산곡선과
CAGR·Sharpe·MDD·승률을 동일가중 매수후보유 벤치마크와 비교합니다. (전략의 객관적 검증 수단 —
실데이터는 토스 API 필요. `--weighting inverse_vol`로 리스크패리티 비중 시뮬레이션.)

## Slack 연동 (인터랙티브 + 브리핑 + 리스크 경보)

`serve` 명령은 하나의 상주 프로세스로 **Slack 슬래시 명령 서버**와 **스케줄러**를 함께 띄웁니다
(analysis-only — 주문 없음).

**슬래시 명령**: `/recommend`(전체 분석), `/screen`(스크리닝만, 무료), `/briefing`(아침 브리핑 즉시),
`/status`, `/help`. 무거운 명령은 3초 내 ack 후 백그라운드 실행해 결과를 `response_url`로 전송합니다.

**자동 푸시 3종**:
- **추천 시그널** — `ALERT_CHANNELS`에 `slack` 추가 시 `run-once`가 서버 없이도 Slack에 푸시.
- **정기 브리핑** — 아침/주간(스케줄러). VIX + 스크리닝 스냅샷.
- **리스크 경보** — 블랙스완(VIX≥임계)·갭다운, 같은 날 중복 억제.

### Slack 앱 설정
1. api.slack.com/apps에서 앱 생성 → **OAuth scopes**: `commands`, `chat:write`(필요시 `chat:write.public`).
2. 워크스페이스 설치 후 **Bot User OAuth Token**(`xoxb-…`) → `SLACK_BOT_TOKEN`, **Signing Secret** →
   `SLACK_SIGNING_SECRET`. 봇을 `SLACK_CHANNEL` 채널에 초대.
3. **Slash Commands** `/recommend`,`/screen`,`/briefing`,`/status`,`/help` 의 Request URL을
   모두 `https://<your-host>/slack/commands`로 지정.
4. `.env`에 `SLACK_ENABLED=true` + 위 키 입력 → `python -m tossai serve`.

### 공개 HTTPS (Slack 요구사항)
uvicorn은 `127.0.0.1:8080`에 바인드되므로 앞단에 **nginx + Let's Encrypt TLS** 리버스 프록시로
443 → `127.0.0.1:8080` 전달(보안그룹 443만 오픈). 로컬 테스트는 `ngrok http 8080` 후 그 HTTPS URL을
슬래시 명령 Request URL에 입력.

서명 검증 로컬 스모크 테스트:
```bash
TS=$(date +%s); BODY='command=/help&text='
SIG="v0=$(printf 'v0:%s:%s' "$TS" "$BODY" | openssl dgst -sha256 -hmac "$SLACK_SIGNING_SECRET" | awk '{print $2}')"
curl -X POST localhost:8080/slack/commands -H "X-Slack-Request-Timestamp: $TS" \
  -H "X-Slack-Signature: $SIG" -H "Content-Type: application/x-www-form-urlencoded" --data "$BODY"
# 200 + /help blocks. 변조하거나 오래된 TS면 401.
```

## 주요 설정 (`.env`)

| 키 | 기본값 | 설명 |
|----|--------|------|
| `MARKET` | `BOTH` | `KRX` / `US` / `BOTH` |
| `CLAUDE_MODEL` | `claude-sonnet-4-6` | 기본 분석 모델 |
| `CLAUDE_MAX_CANDIDATES` | `8` | Claude로 보낼 최대 후보 수(비용 상한) |
| `CLAUDE_MONTHLY_BUDGET_USD` | `20` | 소프트 예산 경고 임계 |
| `ALERT_CHANNELS` | `console` | `console,webhook,smtp,slack` 조합 |
| `WEBHOOK_URL` | – | Slack/Discord incoming webhook (단순 텍스트) |
| `ALERT_MIN_CONFIDENCE` | `0.6` | 이 이상 BUY/SELL만 외부 푸시 |
| `SLACK_ENABLED` | `false` | `serve`로 Slack 서버+스케줄러 활성화 |
| `SLACK_BOT_TOKEN` / `SLACK_SIGNING_SECRET` / `SLACK_CHANNEL` | – | Slack 앱 자격증명·채널 |
| `VIX_BLACKSWAN_THRESHOLD` | `30.0` | 블랙스완 경보 VIX 임계 |
| `RISK_SCAN_INTERVAL_MIN` | `15` | 리스크 스캔 주기(분) |
| `ENABLE_TRADING` | `false` | **반드시 false** (true면 시작 거부) |

스크리닝 임계값(`RSI_PERIOD`, `SMA_FAST/SLOW`, `RSI_OVERBOUGHT`, `VOLUME_RATIO_MIN` 등)도
재배포 없이 `.env`로 튜닝할 수 있습니다.

## EC2 배포

> 무인 자동화 전체 절차(키·Slack 자동푸시·systemd·비용 가드·검증)는 **[`deploy/DEPLOY.md`](deploy/DEPLOY.md)** 런북 참고.

```bash
# EC2에서 (Amazon Linux/Ubuntu)
export REPO_URL=<this repo url>
bash deploy/setup.sh            # venv, 의존성(+fundamentals), /etc/tossai/.env(600), systemd 설치
sudo vi /etc/tossai/.env        # 키 입력 (자동 Slack 푸시는 ALERT_CHANNELS=console,slack)
cd /opt/tossai && ./.venv/bin/python -m tossai doctor   # 스모크 테스트
```

- 스케줄: `deploy/tossai.timer`가 30분마다 `tossai.service`(oneshot `run-once`)를 실행.
  앱이 장 시간을 내부에서 판단하므로 장외 실행은 저렴(Claude 미호출, 알림 억제).
- Slack: `SLACK_ENABLED=true`면 `setup.sh`가 `deploy/tossai-serve.service`(상주 `serve`)를 enable.
  앞단 nginx+TLS 필요(위 "공개 HTTPS" 참고). timer와 독립적으로 동작.
- 시크릿: `/etc/tossai/.env`(root, `chmod 600`)를 systemd `EnvironmentFile`로 주입.
  프로덕션에서는 **AWS SSM Parameter Store / Secrets Manager** 사용을 권장.
- cron을 선호하면 `deploy/crontab.example` 참고.

## 테스트

```bash
./.venv/bin/python -m pytest      # 136 tests, 모든 외부 API 모킹
./.venv/bin/ruff check .
```

- 지표 골든값, 스크리너 통과/탈락·랭킹, 토큰 자동갱신/401 재인증/429 백오프,
  Claude tool-use 파싱·실패 처리·후보 상한, 안전 가드(주문 예외·`ENABLE_TRADING` 거부·
  Slack/scheduler/risk 패키지 주문경로 부재 AST 검증), 장 시간/휴장/DST,
  Slack 서명검증(유효/변조/stale)·블록·dispatch·서버 ack/deferral·SlackNotifier,
  리스크 평가·dedupe·VIX 파싱, 브리핑, 엔드투엔드 파이프라인을 검증합니다.

## 프로젝트 구조

```
src/tossai/
  cli.py            CLI (doctor/screen-only/run-once/run-loop)
  config.py         pydantic-settings + 안전 가드
  models.py         Candle/Candidate/Recommendation 등 도메인 모델
  market/           장 시간·휴장(calendar), 워치리스트(universe)
  toss/             auth(OAuth)·client(시세/캔들)·schemas·orders(비활성 스텁)
  screening/        indicators·screener·regime(VIX 국면)·allocation(리스크패리티)
    strategies/     base·ensemble + 가격기반(technical_swing·dual_momentum·canslim·
                    mean_reversion·trend_breakout·meb_faber·momentum_quality·low_volatility)
                    + 펀더멘털(graham·magic_formula·buffett_quality·piotroski)
  fundamentals/     models·provider(market 라우팅+캐시)·pykrx·yfinance·toss(future hook)
  analysis/         claude_engine(tool-use)·prompts
  pipeline/         orchestrator(전체 흐름)
  output/           report(JSON/콘솔)·alerts(console/webhook/smtp/slack)
  slack/            signature(서명검증)·web_client·blocks·commands·server(FastAPI)·runner
  scheduler/        briefings(아침/주간)·jobs(APScheduler: 브리핑+리스크 스캔)
  risk/             sentiment(VIX)·evaluators(블랙스완/갭다운)·state(dedupe)·models
```

## 로드맵 / 주의

- 정확한 토스 스키마 확정(`doctor`로 검증), 뉴스/펀더멘털 컨텍스트 추가, 백테스트,
  실시간 WebSocket 시세, 휴장일 자동 갱신(`pandas-market-calendars`).
- 휴장일 목록은 `market/calendar.py`의 정적 세트이며 **매년 갱신**이 필요합니다.

## 면책

자동화된 정보 제공용 분석이며 **투자 자문이 아닙니다**. 실제 주문을 내지 않습니다.
투자에는 원금 손실 위험이 있으며 모든 판단과 책임은 사용자 본인에게 있습니다.
