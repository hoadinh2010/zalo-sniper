#!/usr/bin/env python3
"""Interactive CLI to generate config.yaml for ZaloSniper."""
import os
import sys
import urllib.request
import urllib.error
import json
import yaml


# ─── helpers ──────────────────────────────────────────────────────────────────

def ask(prompt: str, default: str = "", required: bool = True) -> str:
    display = f"{prompt} [{default}]: " if default else f"{prompt}: "
    while True:
        val = input(display).strip()
        if not val:
            val = default
        if val or not required:
            return val
        print("  ⚠  Trường này bắt buộc, không được để trống.")


def ask_int(prompt: str, default: int) -> int:
    while True:
        val = input(f"{prompt} [{default}]: ").strip()
        if not val:
            return default
        try:
            return int(val)
        except ValueError:
            print("  ⚠  Phải là số nguyên.")


def ask_bool(prompt: str, default: bool) -> bool:
    while True:
        val = input(f"{prompt} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
        if not val:
            return default
        if val in ("y", "yes"):
            return True
        if val in ("n", "no"):
            return False
        print("  ⚠  Nhập y hoặc n.")


def ask_int_list(prompt: str) -> list:
    print(f"{prompt}")
    print("  (nhập từng ID một, Enter trống để kết thúc)")
    ids = []
    while True:
        val = input("  User ID: ").strip()
        if not val:
            if ids:
                break
            print("  ⚠  Cần ít nhất 1 user ID.")
        else:
            try:
                ids.append(int(val))
                print(f"  ✓  Đã thêm {ids[-1]}")
            except ValueError:
                print("  ⚠  Phải là số nguyên (ví dụ: 123456789).")
    return ids


def tip(text: str) -> None:
    """Print a dimmed tip line."""
    print(f"  💡 {text}")


def section(title: str) -> None:
    width = 50
    print(f"\n{'─' * width}")
    print(f"  {title}")
    print(f"{'─' * width}")


# ─── GitHub repo fetcher ───────────────────────────────────────────────────────

def _github_api(path: str, token: str) -> list | dict | None:
    url = f"https://api.github.com{path}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def fetch_repos_for_owner(owner: str, token: str) -> list[dict]:
    """Try org repos first, fall back to user repos."""
    data = _github_api(f"/orgs/{owner}/repos?per_page=100&sort=updated", token)
    if not isinstance(data, list):
        data = _github_api(f"/users/{owner}/repos?per_page=100&sort=updated", token)
    if not isinstance(data, list):
        return []
    return [{"name": r["name"], "default_branch": r.get("default_branch", "main")} for r in data]


def pick_repos(owner: str, token: str) -> list[dict]:
    """Fetch repos from GitHub and let user pick interactively."""
    print(f"\n  🔍 Đang tải danh sách repo của '{owner}'...")
    repos = fetch_repos_for_owner(owner, token)
    if not repos:
        print("  ⚠  Không tải được repo. Nhập tay bên dưới.")
        return [configure_repo_manual(owner)]

    print(f"\n  Tìm thấy {len(repos)} repo:")
    for i, r in enumerate(repos, 1):
        print(f"    {i:3}. {r['name']}  [{r['default_branch']}]")

    print()
    tip("Nhập số thứ tự các repo muốn theo dõi (cách nhau bởi dấu phẩy, ví dụ: 1,3,5)")
    tip("Hoặc nhấn Enter để nhập tay tên repo.")

    while True:
        val = input("  Chọn repo: ").strip()
        if not val:
            return [configure_repo_manual(owner)]
        try:
            indices = [int(x.strip()) for x in val.split(",")]
            selected = []
            for idx in indices:
                if 1 <= idx <= len(repos):
                    r = repos[idx - 1]
                    tip(f"Mô tả ngắn cho repo '{r['name']}' (vd: Backend API, để trống OK):")
                    desc = input(f"    description [{r['name']}]: ").strip()
                    branch = input(f"    branch [{r['default_branch']}]: ").strip() or r["default_branch"]
                    selected.append({
                        "owner": owner,
                        "name": r["name"],
                        "branch": branch,
                        "description": desc or r["name"],
                    })
                else:
                    print(f"  ⚠  Số {idx} không hợp lệ (phải từ 1 đến {len(repos)}).")
            if selected:
                return selected
        except ValueError:
            print("  ⚠  Nhập số nguyên, ví dụ: 1,3")


def configure_repo_manual(default_owner: str = "") -> dict:
    print()
    tip("Nhập thông tin repo GitHub:")
    owner = ask("    owner (tên org hoặc username GitHub)", default=default_owner)
    name  = ask("    tên repo")
    branch = ask("    branch chính", default="main")
    tip("Mô tả giúp AI chọn đúng repo khi 1 group có nhiều repo.")
    description = ask("    mô tả ngắn (vd: Backend API cho dự án ABC)", required=False)
    return {"owner": owner, "name": name, "branch": branch, "description": description}


# ─── section configurers ──────────────────────────────────────────────────────

def configure_telegram() -> tuple[str, list]:
    section("1/5  Telegram Bot")
    tip("Tạo bot: mở Telegram → tìm @BotFather → /newbot → làm theo hướng dẫn.")
    tip("Bot token có dạng:  1234567890:AAFxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
    bot_token = ask("Bot token")

    print()
    tip("Lấy Telegram user ID của bạn:")
    tip("  Cách 1: nhắn tin cho @userinfobot → nó trả về 'Id: 123456789'.")
    tip("  Cách 2: dùng @RawDataBot, forward bất kỳ tin nhắn nào của bạn.")
    tip("Thêm nhiều user nếu muốn nhiều người có thể approve fix.")
    approved_ids = ask_int_list("Telegram user IDs được phép approve fix")
    return bot_token, approved_ids


def configure_telegram_chat_id() -> int:
    print()
    tip("Lấy Telegram chat_id của group/channel nhận thông báo:")
    tip("  1. Thêm bot vào group Telegram đó (làm admin).")
    tip("  2. Gửi 1 tin nhắn bất kỳ trong group.")
    tip("  3. Mở trình duyệt, truy cập:")
    tip("       https://api.telegram.org/bot<TOKEN>/getUpdates")
    tip("  4. Tìm trường \"chat\":{\"id\": -100xxxxxxxxx} — đó là chat_id.")
    tip("  Chat_id của group luôn là số âm (bắt đầu bằng -100...).")
    return ask_int("  Telegram chat_id", default=0)


def configure_github() -> tuple[str, bool]:
    section("2/5  GitHub")
    tip("Tạo Personal Access Token (classic):")
    tip("  1. Vào github.com → Settings → Developer settings")
    tip("     → Personal access tokens → Tokens (classic) → Generate new token.")
    tip("  2. Chọn scope: [x] repo  (bao gồm read + write + PR)")
    tip("  3. Copy token (bắt đầu bằng ghp_...).")
    tip("Token cần quyền: repo:read, repo:write, pull_requests:write.")
    github_token = ask("GitHub token (ghp_...)")
    pr_enabled = ask_bool("Tự động tạo Pull Request sau khi apply fix?", default=True)
    return github_token, pr_enabled


def configure_gemini() -> str:
    section("3/5  Google Gemini AI")
    tip("Lấy API key miễn phí tại: https://aistudio.google.com/app/apikey")
    tip("  1. Đăng nhập bằng tài khoản Google.")
    tip("  2. Nhấn 'Create API key' → chọn project (hoặc tạo mới).")
    tip("  3. Copy key (bắt đầu bằng AIza...).")
    tip("Gói miễn phí: 15 req/phút, 1 triệu token/ngày — đủ dùng cho bot.")
    tip("Key sẽ được lưu vào file .env (không lưu vào config.yaml).")
    return ask("Gemini API key (AIza...)")


def configure_openproject() -> dict | None:
    print()
    tip("OpenProject: bỏ qua nếu bạn không dùng (nhấn Enter).")
    op_url = ask("  OpenProject URL (vd: https://openproject.example.com)", required=False)
    if not op_url:
        return None

    print()
    tip("Lấy OpenProject API key:")
    tip("  1. Đăng nhập OpenProject → avatar góc trên phải → My Account.")
    tip("  2. Access Tokens → + API access token → Copy.")
    op_api_key = ask("  API key")

    print()
    tip("Lấy project identifier:")
    tip("  Mở project trên OpenProject → xem URL, ví dụ:")
    tip("    https://project.example.com/projects/lfc-ticketing-system")
    tip("  → project identifier là 'lfc-ticketing-system' (có thể là chữ hoặc số).")
    op_project_id = ask("  project identifier (slug hoặc số)")

    return {"url": op_url.rstrip("/"), "api_key": op_api_key, "project_id": op_project_id}


def configure_group(idx: int, github_token: str) -> tuple[str, dict]:
    section(f"Group #{idx}")
    tip("Bot đọc tin nhắn từ group Zalo bằng tài khoản Zalo đã đăng nhập.")
    tip("Điều kiện: tài khoản Zalo đó phải là thành viên của group.")
    tip("Tên group phải khớp CHÍNH XÁC với tên hiển thị trong Zalo Web")
    tip("  (bao gồm dấu, khoảng trắng, chữ hoa/thường).")
    group_name = ask("  Tên group Zalo")

    telegram_chat_id = configure_telegram_chat_id()

    print()
    tip("Mỗi group có thể map với 1 hoặc nhiều GitHub repo.")
    tip("AI sẽ tự chọn repo phù hợp nhất dựa trên nội dung bug report.")
    owner = ask("  GitHub org/username chứa repo")
    repos = pick_repos(owner, github_token)
    print(f"\n  ✓  Đã chọn {len(repos)} repo: {', '.join(r['name'] for r in repos)}")

    if ask_bool("  Thêm repo từ org/username khác?", default=False):
        extra_owner = ask("  GitHub org/username")
        repos += pick_repos(extra_owner, github_token)

    op_cfg = configure_openproject()

    group_cfg: dict = {"repos": repos, "telegram_chat_id": telegram_chat_id}
    if op_cfg:
        group_cfg["openproject"] = op_cfg
    return group_name, group_cfg


def configure_zalo() -> tuple[str, int]:
    section("4/5  Zalo")
    tip("Session Zalo sẽ được lưu vào thư mục này sau khi đăng nhập lần đầu.")
    tip("Không cần thay đổi nếu chạy trên máy local.")
    session_dir = ask("Thư mục lưu session", default="./zalo_session")
    tip("Bot sẽ kiểm tra tin nhắn mới mỗi N giây. Khuyến nghị: 30.")
    poll_interval = ask_int("Tần suất poll (giây)", default=30)
    return session_dir, poll_interval


def configure_groups(github_token: str) -> dict:
    section("5/5  Groups Zalo → Repo mapping")
    tip("Mỗi group Zalo sẽ được theo dõi và map với 1 hoặc nhiều GitHub repo.")
    groups = {}
    idx = 1
    while True:
        name, cfg = configure_group(idx, github_token)
        groups[name] = cfg
        idx += 1
        if not ask_bool("\nThêm group nữa?", default=False):
            break
    return groups


# ─── main ─────────────────────────────────────────────────────────────────────

def main():
    output_path = "config.yaml"
    env_path = ".env"

    print("\n╔══════════════════════════════════════════╗")
    print("║         ZaloSniper — Setup Wizard         ║")
    print("╚══════════════════════════════════════════╝")
    print("\nWizard này sẽ tạo file config.yaml và .env cho bạn.")
    print("Cần chuẩn bị trước:")
    print("  • Telegram bot token  (từ @BotFather)")
    print("  • GitHub Personal Access Token  (scope: repo)")
    print("  • Google Gemini API key  (từ aistudio.google.com)")
    print("  • OpenProject API key  (nếu dùng)")

    if os.path.exists(output_path):
        print(f"\n⚠️  {output_path} đã tồn tại.")
        if not ask_bool("Ghi đè?", default=False):
            print("Hủy.")
            sys.exit(0)

    dry_run = ask_bool("\nBật dry-run mode? (chỉ phân tích, không tạo PR/task)", default=False)

    bot_token, approved_ids = configure_telegram()
    github_token, pr_enabled = configure_github()
    gemini_key = configure_gemini()
    session_dir, poll_interval = configure_zalo()
    groups = configure_groups(github_token)

    # ── write config.yaml ──
    config = {
        "dry_run": dry_run,
        "telegram": {
            "bot_token": bot_token,
            "approved_user_ids": approved_ids,
        },
        "zalo": {
            "session_dir": session_dir,
            "poll_interval_seconds": poll_interval,
        },
        "github": {
            "token": github_token,
            "pr_enabled": pr_enabled,
        },
        "groups": groups,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    # ── write .env ──
    with open(env_path, "w") as f:
        f.write(f"GEMINI_API_KEY={gemini_key}\n")

    print("\n" + "─" * 50)
    print(f"✅  {output_path}  đã được tạo")
    print(f"✅  {env_path}     đã được tạo")
    print("─" * 50)
    print("\n📋  Bước tiếp theo:\n")
    print("  1. Cài dependencies (nếu chưa):")
    print("       pip install -r requirements.txt")
    print("       playwright install chromium")
    print()
    print("  2. Đăng nhập Zalo lần đầu (mở browser, quét QR):")
    print("       python main.py --relogin")
    print()
    print("  3. Chạy bot:")
    print("       source .env && python main.py")
    print()
    print("  Nếu Zalo session hết hạn sau này, chạy lại bước 2.")
    print()


if __name__ == "__main__":
    main()
