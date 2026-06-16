# EC2 무인 자동화 배포 런북 (tossai, analysis-only)

토스 캔들로 주기적 추천을 만들고 Slack에 푸시하는 자동화를 EC2에서 무인 동작시키는 절차입니다.
**주문은 절대 나가지 않습니다** (분석/추천 전용).

> 사전 조건: EC2(Amazon Linux/Ubuntu), Python 3.11, 발급받은 **TOSS_APP_KEY / TOSS_APP_SECRET**,
> **ANTHROPIC_API_KEY**. (`doctor`가 통과하면 토스 연결은 확인된 것.)

---

## 1) 코드 받기 + 부트스트랩

```bash
sudo mkdir -p /opt/tossai && sudo chown "$USER" /opt/tossai
export REPO_URL=https://github.com/shinyeonseon/yeongseon7744.git
bash <(curl -fsSL https://raw.githubusercontent.com/shinyeonseon/yeongseon7744/claude/toss-securities-investment-ai-0lus7s/deploy/setup.sh) || {
  # 또는 직접 clone 후 실행:
  git clone -b claude/toss-securities-investment-ai-0lus7s "$REPO_URL" /opt/tossai
  cd /opt/tossai && bash deploy/setup.sh
}
```

`setup.sh`가 하는 일: venv 생성, 의존성 + `.[fundamentals]`(pykrx/yfinance) 설치,
`/etc/tossai/.env`(chmod 600) 생성, `config/universe.yaml` 준비, systemd 유닛 설치,
`tossai.timer` 활성화.

## 2) 시크릿/설정 입력 — `/etc/tossai/.env`

```bash
sudo nano /etc/tossai/.env
```

최소 입력:
```ini
TOSS_APP_KEY=tsck_live_...
TOSS_APP_SECRET=tssk_live_...
ANTHROPIC_API_KEY=sk-ant-...
MARKET=KRX                 # 또는 US / BOTH
```

**시장 컨텍스트(거시·뉴스·실적)** 는 기본 ON입니다. 종목 뉴스/다음 실적일은 yfinance로
자동 수집되고, 거시 지표(실업률·기준금리·CPI 등)는 FRED 키가 있을 때만 채워집니다(없으면
FOMC 일정만 표시). 끄거나 조정하려면:
```ini
CONTEXT_ENABLED=true          # 전체 토글
FRED_API_KEY=                 # https://fredaccount.stlouisfed.org 에서 무료 발급(선택)
CONTEXT_NEWS_MAX=3            # 종목당 뉴스 헤드라인 수(Claude 토큰 비용에 영향)
```

**자동 Slack 푸시(추천 시그널)를 원하면**:
```ini
ALERT_CHANNELS=console,slack
SLACK_BOT_TOKEN=xoxb-...
SLACK_CHANNEL=C0xxxxxxx     # 봇을 초대한 채널 id
ALERT_MIN_CONFIDENCE=0.6    # 이 이상 BUY/SELL만 푸시
```
이것만으로 `tossai.timer`가 주기적으로 분석해 채널에 올립니다. (서버 불필요)

> **`channel_not_found` / `not_in_channel` 에러가 나면**: ① `SLACK_CHANNEL`을 채널 **ID**
> (`#채널이름`의 우클릭 → 채널 세부정보 맨 아래 `C0XXXXXXX`)로 넣고 ② 그 채널에서 봇을 초대
> (`/invite @봇이름`)하세요. 봇 토큰 스코프에 `chat:write`가 있어야 합니다.

**Slack 슬래시 명령(/recommend 등 인터랙티브)까지 원하면** 추가로:
```ini
SLACK_ENABLED=true
SLACK_SIGNING_SECRET=...
```
→ `setup.sh` 재실행 또는 `sudo systemctl enable --now tossai-serve`.
인터랙티브는 **공개 HTTPS**가 필요 → 앞단에 nginx + Let's Encrypt(443 → 127.0.0.1:8080).
자세한 Slack 앱 설정은 루트 `README.md`의 "Slack 연동" 참고.

## 3) 스모크 테스트

```bash
cd /opt/tossai
./.venv/bin/python -m tossai doctor       # 토큰+시세 1콜 (통과해야 함)
./.venv/bin/python -m tossai screen-only  # 오늘 선별 종목 (무료, Claude 미사용)
```

## 4) 자동화 켜기 / 확인

```bash
sudo systemctl enable --now tossai.timer
systemctl status tossai.timer --no-pager
systemctl list-timers tossai.timer --no-pager
# 첫 실행 로그 (장중이면 분석, 장외면 알림 억제):
journalctl -u tossai.service -n 60 --no-pager
ls -t /opt/tossai/reports | head    # JSON 리포트가 쌓이는지
```

장중에 Slack 채널로 추천이 올라오면 자동화 성공입니다.

## 5) 보유 포트폴리오 조언 Slack 자동화 (선택)

워치리스트 추천과 별개로, **내가 실제 보유한 종목**에 ADD/HOLD/TRIM/SELL 조언을 Slack으로 받습니다.

먼저 `/etc/tossai/.env`에 계좌 시퀀스를 넣습니다(2)의 Slack 설정도 되어 있어야 함):
```ini
TOSS_ACCOUNT_SEQ=1          # 계좌 시퀀스(보통 1). 모르면 GET /api/v1/accounts의 accountSeq
```

**수동/cron 1회성** — `portfolio` 명령이 콘솔 출력 + (slack 채널 설정 시) 자동 Slack 푸시:
```bash
./.venv/bin/python -m tossai portfolio            # 분석 + Slack 푸시
./.venv/bin/python -m tossai portfolio --no-slack # 콘솔만
```
cron으로 하루 1회(장마감 후) 자동 발송 예:
```cron
40 15 * * 1-5  cd /opt/tossai && ./.venv/bin/python -m tossai portfolio >> logs/portfolio.cron.log 2>&1
```
(EC2 타임존이 KST가 아니면 시간을 환산하세요.)

**`serve`(인터랙티브 서버)를 이미 띄웠다면** 스케줄러에 포트폴리오 잡을 넣어 무인 발송:
```ini
PORTFOLIO_SCHEDULE_ENABLED=true
PORTFOLIO_SCHEDULE_TIME=15:40   # 시장 tz 기준 HH:MM (평일 장마감 후)
```
→ `sudo systemctl restart tossai-serve`. (Claude 비용이 들므로 기본 off, 옵트인입니다.)

---

## 비용 주의 (Claude)

`tossai.timer`는 기본 **30분마다** `run-once`를 돌립니다(장중에만 Claude 호출, 장외엔 억제).
하루 누적 호출이 부담되면:

- `/etc/tossai/.env`에서 `CLAUDE_MAX_CANDIDATES`(후보 상한)·`CLAUDE_MONTHLY_BUDGET_USD`(소프트 경고) 조정.
- 또는 빈도를 낮추기 — `sudo systemctl edit tossai.timer`로 `OnCalendar`를 하루 몇 번만:
  ```ini
  [Timer]
  OnCalendar=
  OnCalendar=Mon..Fri 09:05 Asia/Seoul
  OnCalendar=Mon..Fri 12:30 Asia/Seoul
  OnCalendar=Mon..Fri 15:10 Asia/Seoul
  ```
  (`screen-only`는 무료이므로 무제한 가능; 비용은 Claude를 쓰는 `run-once`에서만 발생.)

## 업데이트

```bash
cd /opt/tossai && git pull --ff-only
./.venv/bin/pip install -e ".[fundamentals]"
sudo systemctl restart tossai-serve 2>/dev/null || true
# timer는 다음 주기에 새 코드로 실행됨
```

## 보안
- 시크릿은 `/etc/tossai/.env`(root, chmod 600)에만. 저장소/이미지에 넣지 마세요.
- 프로덕션은 AWS SSM Parameter Store / Secrets Manager 권장.
- 라이브 키가 노출됐다면 토스 개발자센터에서 재발급.
