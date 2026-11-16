#!/usr/bin/env python3
"""把 course-kb MCP 伺服器加進 Claude Desktop 的設定檔。

用法（先完全關閉 Claude Desktop）：
  python install_claude_desktop.py

會做的事：
  1. 找到 Claude Desktop 的設定檔 claude_desktop_config.json
  2. 先備份成 claude_desktop_config.backup-日期時間.json
  3. 只新增（或更新）mcpServers 裡的 course-kb，其他設定一律保留
  4. Python 和 server.py 的路徑自動帶入這台電腦上的實際位置
"""
import datetime, json, os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = "course-kb"


def config_path():
    if sys.platform.startswith("win"):
        return os.path.join(os.environ["APPDATA"], "Claude", "claude_desktop_config.json")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/Claude/claude_desktop_config.json")
    return os.path.expanduser("~/.config/Claude/claude_desktop_config.json")


def main():
    path = config_path()
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        raise SystemExit(f"找不到 Claude Desktop 的設定資料夾：{folder}\n請確認已安裝並開啟過 Claude Desktop。")

    config = {}
    if os.path.exists(path):
        raw = open(path, encoding="utf-8-sig").read().strip()
        if raw:
            try:
                config = json.loads(raw)
            except json.JSONDecodeError as e:
                raise SystemExit(f"設定檔格式有誤，為了安全沒有修改：{e}")
        backup = path.replace(".json", f".backup-{datetime.datetime.now():%Y%m%d-%H%M%S}.json")
        shutil.copy2(path, backup)
        print(f"已備份：{backup}")

    entry = {"command": sys.executable, "args": [os.path.join(HERE, "server.py")]}
    servers = config.setdefault("mcpServers", {})
    action = "更新" if NAME in servers else "新增"
    servers[NAME] = entry

    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:   # UTF-8、不加 BOM
        json.dump(config, f, ensure_ascii=False, indent=2)
    json.load(open(tmp, encoding="utf-8"))          # 寫完再讀一次，確認格式正確才取代
    os.replace(tmp, path)

    print(f"已{action} MCP 伺服器「{NAME}」：")
    print(f"  command: {entry['command']}")
    print(f"  args:    {entry['args'][0]}")
    print(f"其他設定保留 {len([k for k in config if k != 'mcpServers'])} 項。現在可以重新打開 Claude Desktop。")


if __name__ == "__main__":
    main()
