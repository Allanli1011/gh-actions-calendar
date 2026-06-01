# GitHub Actions 定时任务日历

把我所有 GitHub 仓库里 Actions 的 `cron` 定时任务,自动汇总成一个**可订阅的 iCalendar 日历源**。

## 📅 订阅地址

```
https://raw.githubusercontent.com/Allanli1011/gh-actions-calendar/main/github-actions-schedule.ics
```

- **Google 日历**:左侧「其他日历」+ → 从网址 → 粘贴链接 → 添加。
- **Apple 日历**:文件 → 新建日历订阅 → 粘贴链接(可设刷新频率)。

每个事件带 **15 分钟提前提醒**;源文件用 UTC,日历会自动按本地时区(北京 UTC+8)显示。

## 🔄 自动更新原理

`.github/workflows/refresh.yml` 每天 **01:17 UTC**(北京 09:17)运行 `generate_calendar.py`:
扫描我所有非 fork / 非归档仓库的 `.github/workflows/*.yml`,提取每个 `cron`,重新生成
`.ics`,有变化才提交。改了任何 cron、新增定时任务,次日自动反映(Google 对外部订阅
的刷新有数小时延迟;Apple 可手动设更短)。

## ⚙️ 一次性配置:CALENDAR_PAT

脚本要读取**私有仓库**的 cron,需要一个有读取权限的 PAT:

1. **创建 PAT** — GitHub → Settings → Developer settings → Personal access tokens
   - Classic:勾选 `repo`;**或**
   - Fine-grained:Repository access = All repositories,Permissions → Contents: Read-only + Metadata: Read-only。
2. **加为 Secret** — 本仓库 Settings → Secrets and variables → Actions → New repository secret
   - Name: `CALENDAR_PAT`,Value: 粘贴 PAT。
3. **验证** — Actions 页面手动 Run 一次 “Refresh Actions Calendar”。

> 不配 `CALENDAR_PAT`:workflow 仍会跑,但只能扫到**公开仓库**(私有仓库的定时任务会缺失)。
> 首版 `.ics` 已包含全部仓库(本地用有权限的 token 生成并提交)。

## 本地手动生成

```bash
GH_TOKEN=$(gh auth token) python generate_calendar.py --out github-actions-schedule.ics
```
