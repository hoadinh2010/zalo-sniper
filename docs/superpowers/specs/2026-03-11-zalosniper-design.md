# ZaloSniper — Design Document

**Date:** 2026-03-11
**Status:** Approved
**Stack:** Python · Playwright · Claude API · SQLite · Telegram Bot · GitHub API · OpenProject API

---

## Overview

ZaloSniper là một bot tự động giám sát các group Zalo để phát hiện bug report từ người dùng, phân tích root cause trong source code bằng Claude AI, đề xuất và thực hiện fix (khi được approve), thông báo qua Telegram, và tạo task trên OpenProject.

---

## Architecture

**Pattern:** Modular Monolith — một Python process duy nhất, các module giao tiếp qua asyncio EventBus nội bộ.

### Modules

| Module | Trách nhiệm |
|--------|-------------|
| `ZaloListener` | Dùng Playwright poll 10 group Zalo mỗi 30s, lưu tin nhắn mới vào SQLite |
| `AIAnalyzer` | Dùng Claude API phân loại tin nhắn, phát hiện bug report, xác định repo liên quan, phân tích root cause, đề xuất fix |
| `CodeAgent` | Clone/pull repo, đọc code liên quan, apply code patch sau khi được approve |
| `TelegramBot` | Gửi thông báo kết quả phân tích, nhận lệnh approve/reject từ người dùng, hỗ trợ lệnh thủ công |
| `GitHubClient` | Tạo branch, push fix, tạo Pull Request (optional, có thể tắt) |
| `OpenProjectClient` | Tạo work package khi phát hiện bug |
| `MessageStore` | SQLite database lưu tin nhắn, lịch sử phân tích, kết quả fix |
| `ConfigManager` | Đọc config.yaml, quản lý mapping group → repo → telegram |
| `EventBus` | asyncio Queue nội bộ kết nối các module |

---

## Zalo Login & Session Management

### First-run Login
Bot chạy ở **headed mode** (browser hiển thị) để người dùng thực hiện QR scan hoặc đăng nhập phone lần đầu. Sau khi đăng nhập thành công, Playwright lưu toàn bộ session state vào thư mục `zalo_session/` (cookies, localStorage, storage state).

### Session Persistence
Mỗi lần khởi động, bot load session từ `zalo_session/`. Nếu session hợp lệ → chạy headless. Nếu session hết hạn hoặc không hợp lệ:
1. Bot gửi Telegram alert: "Zalo session hết hạn. Chạy lại bot để đăng nhập."
2. Bot dừng ZaloListener, các module khác vẫn hoạt động bình thường.
3. Người dùng chạy `python main.py --relogin` → headed mode, đăng nhập lại.

### Startup Check
Khi khởi động, bot verify session bằng cách truy cập trang Zalo Web. Nếu bị redirect về trang login → coi là session hết hạn.

---

## Data Flow

### Bug Detection & Fix Flow

```
1. ZaloListener poll tin nhắn mới (mỗi 30s)
   → với mỗi group, lấy messages mới hơn last_seen_timestamp
   → kiểm tra deduplication bằng (group_name, zalo_message_id) UNIQUE
   → lưu vào MessageStore (messages table)
   → emit NEW_MESSAGE event

2. AIAnalyzer nhận NEW_MESSAGE
   → gửi tin nhắn gần đây (tối đa 20 messages trong 1 giờ qua) cho Claude
   → Claude phân loại: "bug_report" | "noise"
   → nếu "noise": bỏ qua
   → nếu "bug_report":
     → Claude xác định repo nào bị ảnh hưởng trong danh sách repo của group
     → lưu repo_owner + repo_name đã chọn vào bug_analyses
     → emit BUG_DETECTED event

3. CodeAgent nhận BUG_DETECTED
   → clone/pull repo đã được Claude xác định ở bước 2
   → dùng grep + file tree tìm files liên quan (tối đa 10 files, ~2000 tokens/file)
   → gửi code context cho AIAnalyzer

4. AIAnalyzer phân tích root cause
   → Claude nhận: [tin nhắn + code context]
   → trả về: root_cause, affected_files, proposed_fix_description
   → lưu vào MessageStore (bug_analyses table, status = "pending")

5. TelegramBot gửi thông báo đến Telegram group của group Zalo đó
   → hiển thị: group Zalo, repo đã chọn, summary bug, root cause, đề xuất fix
   → 3 nút inline keyboard:
     [✅ Approve Fix] [❌ Reject] [📋 Task Only]
   → lưu telegram_message_id vào bug_analyses

6a. Nếu APPROVED (trong 30 phút):
   → Kiểm tra status === "pending"; nếu không → bỏ qua (idempotency)
   → Cập nhật status = "approved" ngay lập tức (atomic)
   → AIAnalyzer generate code patch (Claude)
   → CodeAgent apply patch, tạo branch `fix/bug-<id>`, push
   → GitHubClient tạo Pull Request (nếu github_pr_enabled = true trong config)
   → OpenProjectClient tạo work package (project_id từ config của group đó)
   → TelegramBot thông báo: link PR + link OpenProject task
   → Cập nhật status = "done"

6b. Nếu REJECTED:
   → Kiểm tra status === "pending"; nếu không → bỏ qua (idempotency)
   → Cập nhật status = "rejected"
   → TelegramBot xác nhận đã hủy

6c. Nếu TASK ONLY:
   → Kiểm tra status === "pending"; nếu không → bỏ qua (idempotency)
   → Cập nhật status = "task_only"
   → OpenProjectClient tạo work package (status: New)
   → TelegramBot thông báo: link OpenProject task

6d. Nếu timeout (30 phút không phản hồi):
   → background scheduler kiểm tra records có status = "pending" và created_at > 30 phút
   → tự động cập nhật status = "expired"
   → TelegramBot gửi thông báo hủy

7. Xử lý lỗi API (mọi bước)
   → Nếu Claude API lỗi: cập nhật status = "error", lưu error_message, gửi Telegram alert
   → Nếu GitHub API lỗi: cập nhật status = "error", lưu error_message, gửi Telegram alert
   → Nếu OpenProject API lỗi: ghi log, gửi Telegram alert, không fail toàn bộ flow
```

### Multi-Repo Disambiguation Strategy

Khi một group có nhiều repo, Claude nhận danh sách tất cả repo và mô tả ngắn của từng repo (lấy từ GitHub README hoặc config), rồi xác định repo nào khả năng cao nhất bị ảnh hưởng dựa vào nội dung tin nhắn. Kết quả là một repo duy nhất được ghi vào `bug_analyses`. Nếu Claude không thể xác định → chọn repo đầu tiên trong danh sách và ghi chú `repo_selection_reason = "ambiguous"` để người dùng biết.

---

## Configuration

```yaml
# config.yaml
dry_run: false                          # true = chỉ phân tích, không tạo PR/task

telegram:
  bot_token: "..."
  approved_user_ids: [123456789]        # global whitelist — bất kỳ ai trong list có thể approve mọi group

zalo:
  session_dir: "./zalo_session"
  poll_interval_seconds: 30

github:
  token: "..."
  pr_enabled: true                      # false = push branch nhưng không tạo PR

groups:
  "Tên Group Zalo ABC":
    repos:
      - owner: "myorg"
        name: "backend-abc"
        branch: "main"
        description: "Backend API cho dự án ABC"   # giúp Claude chọn đúng repo
      - owner: "myorg"
        name: "frontend-abc"
        branch: "main"
        description: "Frontend React cho dự án ABC"
    telegram_chat_id: -1001234567890
    openproject:
      url: "https://openproject.example.com"
      api_key: "..."
      project_id: 1                    # per-group project_id

  "Tên Group Zalo XYZ":
    repos:
      - owner: "myorg"
        name: "xyz-api"
        branch: "develop"
        description: "API cho dự án XYZ"
    telegram_chat_id: -1009876543210
    openproject:
      url: "https://openproject.example.com"
      api_key: "..."
      project_id: 2                    # project khác cho group này
```

**Authorization scope:** `approved_user_ids` là global — bất kỳ user nào trong list có thể approve fix cho bất kỳ group nào. Phù hợp với setup nhỏ, team có toàn quyền. Nếu cần per-group authorization trong tương lai, thêm `approved_user_ids` vào cấu hình từng group.

---

## Database Schema (SQLite)

```sql
-- Tin nhắn từ Zalo
CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    zalo_message_id TEXT,               -- ID của tin nhắn từ Zalo (nếu có)
    group_name TEXT NOT NULL,
    sender TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp DATETIME NOT NULL,
    processed BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    -- Primary dedup: khi Zalo Web expose message ID
    UNIQUE(group_name, zalo_message_id),
    -- Fallback dedup: khi zalo_message_id = NULL (SQLite treats NULLs as distinct in UNIQUE,
    -- nên cần index riêng dưới đây để enforce)
    UNIQUE(group_name, sender, content, timestamp)
);

-- Kết quả phân tích bug
CREATE TABLE bug_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_ids TEXT NOT NULL,              -- JSON array of message ids
    group_name TEXT NOT NULL,
    repo_owner TEXT,
    repo_name TEXT,
    repo_selection_reason TEXT,             -- "matched" | "ambiguous"
    status TEXT NOT NULL DEFAULT 'pending', -- pending|approved|rejected|expired|task_only|done|error
    claude_summary TEXT,
    root_cause TEXT,
    proposed_fix TEXT,
    code_patch TEXT,
    error_message TEXT,                     -- lưu error nếu status = "error"
    retry_count INTEGER DEFAULT 0,          -- số lần retry Claude API
    pr_url TEXT,
    pr_number INTEGER,
    op_work_package_id INTEGER,
    op_work_package_url TEXT,
    telegram_message_id INTEGER,
    approved_by INTEGER,                    -- Telegram user_id (set cho cả approve, reject, task_only)
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Trigger để tự động cập nhật updated_at
CREATE TRIGGER update_bug_analyses_updated_at
AFTER UPDATE ON bug_analyses
BEGIN
    UPDATE bug_analyses SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
```

**Deduplication:** SQLite treats NULL values as distinct in UNIQUE constraints, nên cần hai UNIQUE indexes riêng biệt: một cho `zalo_message_id` (khi Zalo expose), một cho `(group_name, sender, content, timestamp)` (fallback). Application layer dùng `INSERT OR IGNORE` để tránh lỗi constraint khi insert duplicate.

---

## Telegram Bot Commands

| Lệnh | Mô tả |
|------|-------|
| `/status` | Trạng thái bot, số group đang monitor, Zalo session status |
| `/groups` | Danh sách group Zalo và repo mapping |
| `/summary [group_name]` | Tổng hợp tin nhắn trong 24 giờ qua từ group bằng Claude |
| `/ask [group_name] [câu hỏi]` | Hỏi Claude về lịch sử tin nhắn của group (free-form Q&A) |
| `/history [group_name]` | Lịch sử bug đã phát hiện và xử lý (30 ngày gần nhất) |
| `/pending` | Danh sách bug đang chờ approve |

**`/summary` scope:** Lấy tất cả messages trong 24 giờ qua của group đó, gửi cho Claude để tổng hợp dạng bullet points.

**`/ask` scope:** Free-form Q&A — người dùng hỏi bất kỳ câu gì, Claude tìm trong toàn bộ message history của group đó để trả lời. Giới hạn context: 7 ngày gần nhất hoặc 500 messages gần nhất, lấy giá trị nhỏ hơn.

---

## Safety Constraints

1. **Human-in-the-loop bắt buộc:** Bot KHÔNG BAO GIỜ tự commit/push code không có approve từ Telegram
2. **Whitelist approve:** Chỉ `approved_user_ids` trong config mới có thể approve fix (global scope)
3. **Idempotency:** Mỗi `bug_analysis` chỉ được xử lý một lần — callback thứ hai bị bỏ qua nếu status đã thay đổi
4. **Timeout tự động:** Mỗi pending fix tự hủy sau 30 phút không có phản hồi
5. **Branch isolation:** Luôn tạo branch mới (`fix/bug-<id>`), không bao giờ push thẳng vào main/master/develop
6. **Dry-run mode:** `dry_run: true` trong config để chỉ phân tích, không tạo PR hay task
7. **PR optional:** `github.pr_enabled: false` để chỉ push branch, không tạo PR

---

## Error Handling

| Lỗi | Hành động |
|-----|-----------|
| Claude API rate limit / timeout | Giữ `status = "pending"`, tăng `retry_count`, retry tối đa 3 lần với backoff 5/10/20 phút. Sau 3 lần thất bại cập nhật `status = "error"` và gửi Telegram alert |
| GitHub token thiếu quyền | Cập nhật `status = "error"`, gửi Telegram alert với hướng dẫn |
| OpenProject không kết nối được | Ghi log, gửi Telegram alert, KHÔNG fail toàn bộ flow (fix vẫn apply) |
| Zalo session hết hạn | Dừng ZaloListener, gửi Telegram alert, chờ relogin thủ công |
| Zalo UI thay đổi (selector bị break) | Log error, gửi Telegram alert, tiếp tục poll (sẽ fail silently từng lần) |

---

## Technical Risks & Mitigations

| Rủi ro | Giải pháp |
|--------|-----------|
| Zalo thay đổi UI → Playwright selectors bị break | Tách selectors vào `zalo_selectors.py`, alert qua Telegram khi fail |
| Zalo session hết hạn | Lưu session state vào `zalo_session/`, detect và alert, hỗ trợ `--relogin` flag |
| Claude context window limit với repo lớn | Tối đa 10 files, ~2000 tokens/file ≈ 20k tokens code. Model mục tiêu: claude-sonnet-4-6 |
| Chạy local → phụ thuộc máy tính luôn bật | Thiết kế stateless, dễ restart; state lưu trong SQLite |
| Cost Claude API | ~20k tokens/analysis. Ước tính ~$0.06/bug report với Sonnet. Chấp nhận được cho tần suất thấp |

---

## Target Model

**Claude claude-sonnet-4-6** — cân bằng giữa capability và cost. Không dùng Opus cho phân tích bug thông thường (tốn kém), giữ Opus cho các case phức tạp nếu cần.

---

## Project Structure

```
ZaloSniper/
├── config.yaml                    # Cấu hình chính (gitignore)
├── config.example.yaml            # Template cấu hình
├── main.py                        # Entry point
├── requirements.txt
├── zalo_session/                  # Playwright session storage (gitignore)
├── zalosniper/
│   ├── __init__.py
│   ├── core/
│   │   ├── event_bus.py           # asyncio EventBus
│   │   ├── config.py              # ConfigManager
│   │   └── database.py            # SQLite setup & migrations
│   ├── modules/
│   │   ├── zalo_listener.py       # Playwright Zalo bot
│   │   ├── zalo_selectors.py      # CSS selectors (isolated cho dễ update)
│   │   ├── ai_analyzer.py         # Claude API integration
│   │   ├── code_agent.py          # Repo clone/read/patch
│   │   ├── telegram_bot.py        # Telegram bot handler
│   │   ├── github_client.py       # GitHub API client
│   │   └── openproject_client.py  # OpenProject API client
│   └── models/
│       ├── message.py
│       └── bug_analysis.py
└── docs/
    └── superpowers/
        └── specs/
            └── 2026-03-11-zalosniper-design.md
```
