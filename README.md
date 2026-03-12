# ZaloSniper 🎯

Bot tự động giám sát nhóm Zalo, phát hiện bug/issue bằng AI, tạo task trên OpenProject và thông báo qua Telegram.

## Tổng quan

ZaloSniper lắng nghe tin nhắn trong các nhóm Zalo (qua Zalo Web), sử dụng AI (Gemini / z.ai / OpenAI-compatible) để phân tích và phân loại tin nhắn thành bug report, feature request hoặc hội thoại thông thường. Khi phát hiện issue, bot tự động:

1. **Phân tích** tin nhắn bằng AI (triage: bug / feature / ignore)
2. **Tạo task** trên OpenProject với đầy đủ mô tả
3. **Upload hình ảnh** đính kèm từ Zalo lên OpenProject
4. **Thông báo** qua Telegram với nút approve/reject
5. **Cập nhật** issue cũ khi cuộc hội thoại tiếp tục về cùng một vấn đề
6. **Tạo PR** trên GitHub (tùy chọn) khi bug được approve

## Kiến trúc

```
Zalo Web (Playwright) → Event Bus → Orchestrator → AI Analyzer
                                        ↓
                              ┌─────────┼──────────┐
                              ↓         ↓          ↓
                         OpenProject  Telegram   GitHub
                         (task+img)   (notify)   (PR)
```

**Stack:** Python 3.11+ | FastAPI | Playwright | SQLite (aiosqlite) | Jinja2

## Tính năng

### Đã hoàn thành ✅

| Tính năng | Mô tả |
|-----------|-------|
| **Zalo Listener** | Scrape tin nhắn từ Zalo Web bằng Playwright, hỗ trợ nhiều nhóm |
| **AI Triage** | Phân tích tin nhắn bằng Gemini / z.ai / OpenAI-compatible |
| **OpenProject Integration** | Tự động tạo work package, upload hình ảnh đính kèm |
| **Telegram Bot** | Thông báo real-time, inline keyboard approve/reject/assign |
| **Bug Update Detection** | AI nhận diện tin nhắn tiếp theo thuộc bug cũ → cập nhật thay vì tạo mới |
| **Image Capture** | Tải hình ảnh từ Zalo về local, lưu DB, upload lên OpenProject |
| **Web Dashboard** | Quản lý settings, xem chat, xem bug list, mapping group↔project |
| **Multi AI Provider** | Hỗ trợ Gemini, z.ai (GLM), OpenAI-compatible với hot-reload |
| **Rate Limiter** | Global rate limit 30s giữa các AI call, tránh 429 |
| **GitHub PR** | Tự động tạo PR khi approve bug (tùy chọn) |
| **Auth Dashboard** | Đăng nhập bằng mật khẩu, đổi mật khẩu từ UI |

### Đang phát triển 🚧

| Tính năng | Mô tả | Ưu tiên |
|-----------|-------|---------|
| **Quản lý Zalo Account** | UI để thêm/xóa/relogin tài khoản Zalo | Cao |
| **Group ↔ Project Mapping UI** | Giao diện kéo thả mapping nhóm Zalo → OpenProject project + GitHub repo | Cao |
| **Multi-account Zalo** | Hỗ trợ nhiều tài khoản Zalo cùng lúc | Trung bình |
| **Notification Rules** | Tùy chỉnh rule thông báo theo nhóm/loại issue | Trung bình |
| **Analytics Dashboard** | Thống kê bug theo thời gian, nhóm, trạng thái | Thấp |
| **Webhook Integration** | Nhận webhook từ OpenProject khi task thay đổi trạng thái | Thấp |
| **Docker Deployment** | Dockerfile + docker-compose cho production | Cao |
| **Auto-assign** | Tự động assign task dựa trên nội dung và lịch sử | Trung bình |

## Cài đặt

### Yêu cầu

- Python 3.11+
- Chromium browser (cho Playwright)
- Tài khoản Zalo đã đăng nhập trên Zalo Web

### Bước 1: Clone và cài đặt

```bash
git clone https://github.com/hoadinh2010/zalo-sniper.git
cd zalo-sniper
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
playwright install chromium
```

### Bước 2: Cấu hình

Tạo file `config.yaml`:

```yaml
zalo_poll_interval: 30        # Khoảng thời gian poll Zalo (giây)
dashboard_port: 8080          # Port cho web dashboard

ai:
  provider: gemini             # gemini | zai | openai_compatible
  model: gemini-2.0-flash
  gemini_api_key: "AIza..."

github_token: "ghp_..."       # GitHub Personal Access Token
telegram_bot_token: "123:ABC" # Telegram Bot Token

openproject:
  url: "https://your-op.example.com"
  api_key: "your-api-key"

approved_user_ids:             # Telegram user IDs được phép approve
  - 123456789

groups:                        # Mapping nhóm Zalo
  "Tên nhóm Zalo":
    telegram_chat_id: -100123456
    openproject_project: "project-slug"
    github_repo: "owner/repo"
```

Hoặc dùng `.env`:

```env
GEMINI_API_KEY=AIza...
ZAI_API_KEY=...
GITHUB_TOKEN=ghp_...
TELEGRAM_BOT_TOKEN=123:ABC...
```

### Bước 3: Đăng nhập Zalo lần đầu

```bash
python main.py --relogin --headed
```

Quét mã QR trên Zalo Web để đăng nhập. Session sẽ được lưu tại `zalo_session/`.

### Bước 4: Chạy bot

```bash
python main.py
```

Các option:

```
--config PATH    Đường dẫn config.yaml (mặc định: config.yaml)
--relogin        Đăng nhập lại Zalo
--headed         Hiển thị browser (debug)
--ai PROVIDER    Override AI provider: gemini | zai | openai_compatible
--model MODEL    Override AI model
```

### Bước 5: Truy cập Dashboard

Mở `http://localhost:8080` — mật khẩu mặc định: `admin` (đổi ngay trong Settings).

## Cấu trúc dự án

```
zalosniper/
├── core/
│   ├── config.py          # ConfigManager - load/save settings từ DB
│   ├── database.py        # SQLite database layer
│   ├── event_bus.py       # Pub/sub event system
│   └── orchestrator.py    # Pipeline xử lý chính
├── models/
│   ├── message.py         # Message dataclass
│   └── analysis.py        # BugAnalysis dataclass
├── modules/
│   ├── ai_analyzer.py     # Multi-provider AI triage
│   ├── code_agent.py      # Code analysis agent
│   ├── github_client.py   # GitHub API wrapper
│   ├── openproject_client.py  # OpenProject API wrapper
│   ├── telegram_bot.py    # Telegram notification bot
│   ├── zalo_listener.py   # Zalo Web scraper (Playwright)
│   └── zalo_selectors.py  # CSS selectors cho Zalo Web
├── web/
│   ├── app.py             # FastAPI app factory
│   ├── auth.py            # Authentication (bcrypt)
│   ├── log_handler.py     # Ring buffer log handler
│   ├── routes/
│   │   ├── api.py         # REST API endpoints
│   │   └── pages.py       # HTML page routes
│   ├── static/
│   │   └── style.css      # Dashboard CSS
│   └── templates/         # Jinja2 templates
│       ├── base.html
│       ├── dashboard.html
│       ├── chat.html
│       ├── bugs.html
│       ├── keys.html
│       ├── mapping.html
│       └── login.html
├── tests/                 # pytest test suite
└── main.py                # Entry point
```

## Progress

| Giai đoạn | Trạng thái | Mô tả |
|-----------|-----------|-------|
| **Phase 1: Core** | ✅ Done | Zalo listener, AI triage, Telegram notify |
| **Phase 2: Integration** | ✅ Done | OpenProject task, GitHub PR, image capture |
| **Phase 3: Dashboard** | ✅ Done | Web UI: settings, chat, bugs, mapping |
| **Phase 4: Intelligence** | ✅ Done | Bug update detection, rate limiting, hot-reload |
| **Phase 5: Management UI** | 🚧 In Progress | Quản lý account, group mapping nâng cao |
| **Phase 6: Production** | 📋 Planned | Docker, monitoring, auto-scaling |

## Roadmap

| Thời gian | Milestone | Tính năng |
|-----------|-----------|-----------|
| **T3/2026** | v0.5 - Management UI | Quản lý Zalo account, group↔project mapping UI |
| **T4/2026** | v0.6 - Production Ready | Docker deployment, health checks, backup/restore |
| **T5/2026** | v0.7 - Analytics | Dashboard thống kê, báo cáo bug trends |
| **T6/2026** | v0.8 - Automation | Auto-assign, notification rules, webhook |
| **Q3/2026** | v1.0 - Stable | Multi-account Zalo, plugin system |

## API Endpoints

| Method | Path | Mô tả |
|--------|------|-------|
| GET | `/api/stats` | Thống kê tổng quan |
| GET | `/api/messages?group=...` | Lấy tin nhắn theo nhóm |
| GET | `/api/bugs` | Danh sách bug analyses |
| POST | `/api/bugs/{id}/action` | Approve/reject bug |
| GET | `/api/settings` | Lấy settings |
| POST | `/api/settings` | Cập nhật settings |
| POST | `/api/auth/login` | Đăng nhập |
| POST | `/api/auth/change-password` | Đổi mật khẩu |

## License

MIT

## Tác giả

**Hoa Dinh** — [@hoadinh2010](https://github.com/hoadinh2010)
