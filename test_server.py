#!/usr/bin/env python3
"""自動測試：扮演 MCP 客戶端（例如 Claude Desktop），啟動 server.py，依序送出協定訊息並檢查回應。

用法：python test_server.py
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))


class Client:
    def __init__(self):
        self.p = subprocess.Popen([sys.executable, os.path.join(HERE, "server.py")],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.next_id = 0

    def send(self, method, params=None, notify=False):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self.next_id += 1
            msg["id"] = self.next_id
        self.p.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"))
        self.p.stdin.flush()
        if notify:
            return None
        return json.loads(self.p.stdout.readline().decode("utf-8"))

    def raw(self, text):
        self.p.stdin.write((text + "\n").encode("utf-8"))
        self.p.stdin.flush()
        return json.loads(self.p.stdout.readline().decode("utf-8"))

    def close(self):
        self.p.stdin.close()
        self.p.wait(timeout=5)


passed = failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"✓ {label}")
    else:
        failed += 1
        print(f"✗ {label}  {detail}")


def text_of(resp):
    return resp["result"]["content"][0]["text"]


c = Client()

# 1. 握手
r = c.send("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                          "clientInfo": {"name": "test-client", "version": "1.0"}})
check("initialize 回傳相同的協定版本", r["result"]["protocolVersion"] == "2025-06-18", r)
check("initialize 宣告支援 tools", "tools" in r["result"]["capabilities"], r)
check("initialized 通知不回應（下一則回應仍對得上 id）", c.send("notifications/initialized", notify=True) is None)
check("ping 回傳空結果", c.send("ping")["result"] == {})

# 2. 列出工具
r = c.send("tools/list")
names = [t["name"] for t in r["result"]["tools"]]
check("tools/list 有 3 個工具", sorted(names) == ["get_document", "list_documents", "search_course_docs"], names)
check("每個工具都有 inputSchema", all("inputSchema" in t for t in r["result"]["tools"]))

# 3. 呼叫工具
r = c.send("tools/call", {"name": "list_documents", "arguments": {}})
check("list_documents 列出退費規定", "refund" in text_of(r) and "退費規定" in text_of(r))

r = c.send("tools/call", {"name": "search_course_docs", "arguments": {"query": "開課後兩週想退費可以退多少？"}})
t = text_of(r)
check("搜尋退費 → 第一段是 refund#2", t.index("[refund#2]") < t.index("[refund#1]") if "[refund#1]" in t else "[refund#2]" in t, t[:200])
check("搜尋結果含原文「退還已繳費用的 50%」", "退還已繳費用的 50%" in t)

r = c.send("tools/call", {"name": "search_course_docs", "arguments": {"query": "錯過一堂課怎麼補？", "top_k": 1}})
check("同義詞擴充：錯過 → 找到缺課補課段落", "[class_modes#1]" in text_of(r) and "缺課" in text_of(r), text_of(r)[:120])

r = c.send("tools/call", {"name": "search_course_docs", "arguments": {"query": "有沒有日文課？"}})
check("知識庫沒有的內容 → 回傳找不到", "找不到" in text_of(r) and not r["result"]["isError"])

r = c.send("tools/call", {"name": "get_document", "arguments": {"name": "scholarship"}})
check("get_document 回傳完整文件", "高分獎學金" in text_of(r) and "申請期限" in text_of(r))

# 4. 錯誤處理
r = c.send("tools/call", {"name": "search_course_docs", "arguments": {"query": ""}})
check("空白查詢 → isError=true 並說明原因", r["result"]["isError"] and "不可以是空的" in text_of(r))
r = c.send("tools/call", {"name": "get_document", "arguments": {"name": "no_such_doc"}})
check("不存在的文件 → isError=true 並列出可用文件", r["result"]["isError"] and "pricing" in text_of(r))
r = c.send("tools/call", {"name": "no_such_tool", "arguments": {}})
check("未知工具 → JSON-RPC 錯誤 -32602", r.get("error", {}).get("code") == -32602, r)
r = c.send("resources/list")
check("不支援的方法 → JSON-RPC 錯誤 -32601", r.get("error", {}).get("code") == -32601, r)
r = c.raw("{這不是 JSON")
check("格式錯誤的訊息 → -32700，伺服器不中斷", r.get("error", {}).get("code") == -32700, r)
check("錯誤之後伺服器仍可正常回應", c.send("ping")["result"] == {})

c.close()
print(f"\n{passed} 項通過，{failed} 項失敗")
sys.exit(1 if failed else 0)
