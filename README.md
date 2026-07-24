# 每日早间情报 Bot

每天首尔时间 AM 05:30 自动生成金融与国际政治情报摘要，推送到 Telegram。
行情数字走 yfinance 硬拉，新闻由 Gemini + Google 搜索检索并摘要。

## 部署步骤

1. 上传本仓库到 GitHub（新建仓库后把所有文件推上去）
2. 打开仓库 **Settings → Secrets and variables → Actions → New repository secret**，
   添加以下密钥：

   | 名称 | 说明 | 是否必填 |
   |------|------|----------|
   | `GEMINI_API_KEY` | Google AI Studio 获取 | 必填 |
   | `GEMINI_MODEL` | 模型名，如 `gemini-3.6-flash`（不填则用默认值） | 可选 |
   | `TELEGRAM_BOT_TOKEN` | 通过 @BotFather 创建 bot 获取 | 必填 |
   | `TELEGRAM_CHAT_ID` | 见下方获取方式 | 必填 |
   | `ALPHA_VANTAGE_KEY` | 预留，暂未使用 | 可选 |

3. **获取 TELEGRAM_CHAT_ID**：先给你的 bot 发一条任意消息，然后浏览器打开
   `https://api.telegram.org/bot<你的TOKEN>/getUpdates`，
   在返回的 JSON 里找 `chat.id`。

4. 定时任务已在 `.github/workflows/daily.yml` 设为 `cron: '30 20 * * *'`
   （UTC 20:30 = 首尔 05:30），无需改动。

## 手动测试

仓库 **Actions 页面 → Daily Intel Brief → Run workflow**，
跑一次确认 Telegram 能收到消息。

## 注意事项

- **模型名**：默认 `gemini-3.6-flash`。若运行报 "model not found"，
  说明该模型名不可用，去 Google AI Studio 查当前可用模型，
  改 `GEMINI_MODEL` 这个 Secret 即可（不用改代码）。
- **免费数据源**：CNN Fear&Greed、CBOE Put/Call 的免费接口可能变动或失效，
  失效时对应字段会显示 error / 由 LLM 检索兜底。
- **定时延迟**：GitHub Actions 定时任务常有 5–15 分钟延迟，属正常现象。

## 目录结构

```
daily-intel-bot/
├── .github/workflows/daily.yml   # 定时任务
├── src/
│   ├── main.py                   # 入口
│   ├── market_data.py            # 行情硬拉
│   ├── gemini_client.py          # Gemini 调用 + Prompt
│   └── telegram_sender.py        # 推送
├── requirements.txt
└── README.md
```
