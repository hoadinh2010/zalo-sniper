#!/usr/bin/env python3
"""Interactive CLI to generate config.yaml for ZaloSniper."""
import os
import sys
import yaml


def ask(prompt: str, default: str = "", required: bool = True) -> str:
    display = f"{prompt} [{default}]: " if default else f"{prompt}: "
    while True:
        val = input(display).strip()
        if not val:
            val = default
        if val or not required:
            return val
        print("  (bắt buộc, không được để trống)")


def ask_int(prompt: str, default: int) -> int:
    while True:
        val = input(f"{prompt} [{default}]: ").strip()
        if not val:
            return default
        try:
            return int(val)
        except ValueError:
            print("  (nhập số nguyên)")


def ask_bool(prompt: str, default: bool) -> bool:
    d = "y" if default else "n"
    while True:
        val = input(f"{prompt} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
        if not val:
            return default
        if val in ("y", "yes"):
            return True
        if val in ("n", "no"):
            return False
        print("  (nhập y hoặc n)")


def ask_int_list(prompt: str) -> list:
    print(f"{prompt} (nhập từng ID, Enter để kết thúc):")
    ids = []
    while True:
        val = input("  User ID: ").strip()
        if not val:
            break
        try:
            ids.append(int(val))
        except ValueError:
            print("  (phải là số nguyên)")
    return ids


def configure_repo() -> dict:
    print()
    owner = ask("    GitHub owner (org hoặc username)")
    name = ask("    Tên repo")
    branch = ask("    Branch mặc định", default="main")
    description = ask("    Mô tả ngắn (giúp AI chọn đúng repo)", required=False)
    return {"owner": owner, "name": name, "branch": branch, "description": description}


def configure_group() -> tuple[str, dict]:
    print()
    group_name = ask("  Tên group Zalo (chính xác như trên Zalo)")
    telegram_chat_id = ask_int("  Telegram chat_id để nhận thông báo", default=0)

    repos = []
    print("  Cấu hình repos (Enter để kết thúc thêm repo):")
    while True:
        print(f"    --- Repo #{len(repos) + 1} ---")
        repo = configure_repo()
        repos.append(repo)
        if not ask_bool("    Thêm repo nữa?", default=False):
            break

    op_url = ask("  OpenProject URL (bỏ qua nếu không dùng)", required=False)
    op_api_key = ""
    op_project_id = 0
    if op_url:
        op_api_key = ask("  OpenProject API key")
        op_project_id = ask_int("  OpenProject project_id", default=1)

    group_cfg: dict = {
        "repos": repos,
        "telegram_chat_id": telegram_chat_id,
    }
    if op_url:
        group_cfg["openproject"] = {
            "url": op_url,
            "api_key": op_api_key,
            "project_id": op_project_id,
        }
    return group_name, group_cfg


def main():
    output_path = "config.yaml"
    if os.path.exists(output_path):
        print(f"⚠️  {output_path} đã tồn tại.")
        if not ask_bool("Ghi đè?", default=False):
            print("Hủy.")
            sys.exit(0)

    print("\n=== ZaloSniper Setup ===\n")

    # --- Global ---
    dry_run = ask_bool("Dry-run mode? (chỉ phân tích, không tạo PR/task)", default=False)

    # --- Telegram ---
    print("\n--- Telegram ---")
    print("Tạo bot tại @BotFather, lấy token.")
    bot_token = ask("Bot token")
    print("Lấy user ID của bạn từ @userinfobot.")
    approved_ids = ask_int_list("Telegram user IDs được phép approve fix")
    if not approved_ids:
        print("⚠️  Không có user nào được approve — bot sẽ không thể nhận lệnh.")

    # --- Zalo ---
    print("\n--- Zalo ---")
    session_dir = ask("Thư mục lưu Zalo session", default="./zalo_session")
    poll_interval = ask_int("Tần suất poll tin nhắn (giây)", default=30)

    # --- GitHub ---
    print("\n--- GitHub ---")
    print("Tạo Personal Access Token tại github.com/settings/tokens (scope: repo).")
    github_token = ask("GitHub token")
    pr_enabled = ask_bool("Tự động tạo Pull Request khi approve?", default=True)

    # --- Anthropic ---
    print("\n--- Claude AI ---")
    print("Lấy API key tại console.anthropic.com.")
    anthropic_key = ask("Anthropic API key (lưu vào .env, không lưu vào config.yaml)")

    # --- Groups ---
    print("\n--- Groups Zalo ---")
    groups = {}
    while True:
        print(f"\n  === Group #{len(groups) + 1} ===")
        name, cfg = configure_group()
        groups[name] = cfg
        if not ask_bool("\nThêm group nữa?", default=False):
            break

    # --- Build config ---
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

    # Write config.yaml
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    print(f"\n✅ Đã lưu {output_path}")

    # Write .env
    env_path = ".env"
    with open(env_path, "w") as f:
        f.write(f"ANTHROPIC_API_KEY={anthropic_key}\n")
    print(f"✅ Đã lưu {env_path}")

    # Summary
    print("\n=== Bước tiếp theo ===")
    print("1. Đăng nhập Zalo lần đầu:")
    print("     python main.py --relogin")
    print("2. Chạy bot:")
    print("     source .env && python main.py")
    print("   hoặc:")
    print("     export ANTHROPIC_API_KEY=... && python main.py")


if __name__ == "__main__":
    main()
