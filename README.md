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

| **Zalo Account Management** | UI quản lý session Zalo, đăng nhập QR từ dashboard |
| **Notification Rules** | Tùy chỉnh rule thông báo per-group: tự tạo OP task, gửi Telegram |
| **Analytics Dashboard** | Thống kê bug theo ngày/group/trạng thái với SVG charts |
| **Auto-assign** | Tự gán người xử lý trên OP dựa trên keyword matching |
| **Webhook Integration** | Nhận webhook từ OpenProject, đồng bộ trạng thái bug |
| **Docker Deployment** | Dockerfile + docker-compose cho production |
| **Multi-account Zalo** | DB + UI quản lý nhiều tài khoản Zalo |
| **OP Test Connection** | Nút test kết nối OpenProject trong mapping UI |

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
| **Phase 5: Management UI** | ✅ Done | Account management, notification rules, analytics, auto-assign |
| **Phase 6: Production** | ✅ Done | Docker, webhook, multi-account foundation |

## Roadmap

| Thời gian | Milestone | Tính năng | Trạng thái |
|-----------|-----------|-----------|-----------|
| **T3/2026** | v0.5 - Management UI | Zalo account UI, group mapping, OP test connection | ✅ Done |
| **T3/2026** | v0.6 - Intelligence | Analytics dashboard, notification rules, auto-assign | ✅ Done |
| **T3/2026** | v0.7 - Production | Docker deployment, webhook integration | ✅ Done |
| **T4/2026** | v0.8 - Multi-account | Multiple Zalo browser contexts, per-account monitoring | 🚧 Planned |
| **T5/2026** | v1.0 - Stable | Plugin system, custom AI prompts, backup/restore | 📋 Planned |

## API Endpoints

| Method | Path | Mô tả |
|--------|------|-------|
| POST | `/api/auth/login` | Đăng nhập dashboard |
| POST | `/api/auth/logout` | Đăng xuất |
| POST | `/api/auth/change-password` | Đổi mật khẩu |
| GET | `/api/status` | Trạng thái bot + thống kê |
| GET | `/api/settings` | Lấy settings |
| POST | `/api/settings` | Cập nhật settings (hot-reload AI) |
| GET | `/api/groups` | Danh sách groups |
| POST | `/api/groups` | Thêm group |
| PATCH | `/api/groups/{id}` | Cập nhật group |
| DELETE | `/api/groups/{id}` | Xóa group |
| GET | `/api/groups/{id}/repos` | Repos của group |
| POST | `/api/groups/{id}/repos` | Thêm repo |
| PUT | `/api/groups/{id}/repos/{rid}` | Cập nhật repo |
| DELETE | `/api/groups/{id}/repos/{rid}` | Xóa repo |
| GET | `/api/groups/{id}/openproject` | OP config của group |
| PUT | `/api/groups/{id}/openproject` | Lưu OP config |
| POST | `/api/groups/{id}/openproject/test` | Test kết nối OP |
| GET | `/api/groups/{id}/notifications` | Notification rules |
| PUT | `/api/groups/{id}/notifications` | Cập nhật notification rules |
| GET | `/api/groups/{id}/assignment-rules` | Auto-assign rules |
| POST | `/api/groups/{id}/assignment-rules` | Thêm auto-assign rule |
| DELETE | `/api/assignment-rules/{id}` | Xóa auto-assign rule |
| GET | `/api/analytics?period=7` | Analytics (7/30/90 ngày) |
| GET | `/api/chat` | Danh sách groups có chat |
| GET | `/api/chat/{group}` | Tin nhắn của group |
| DELETE | `/api/analyses/{id}` | Xóa bug analysis |
| POST | `/api/analyses/{id}/status` | Cập nhật trạng thái bug |
| POST | `/api/analyses/{id}/create-op-task` | Tạo OP task thủ công |
| GET | `/api/analyses/{id}/op-info` | Thông tin OP work package |
| GET | `/api/zalo/status` | Trạng thái Zalo session |
| POST | `/api/zalo/login` | Đăng nhập Zalo (QR code) |
| GET | `/api/zalo/login-status` | Kiểm tra login hoàn tất |
| GET | `/api/zalo/accounts` | Danh sách Zalo accounts |
| POST | `/api/zalo/accounts` | Thêm Zalo account |
| DELETE | `/api/zalo/accounts/{id}` | Xóa Zalo account |
| GET | `/api/github/repos` | Danh sách GitHub repos |
| POST | `/api/webhooks/openproject` | Webhook từ OpenProject |
| GET | `/api/logs` | System logs |

## License

MIT

## Tác giả

**Hoa Dinh** — [@hoadinh2010](https://github.com/hoadinh2010)
