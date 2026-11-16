#!/usr/bin/env python3
"""課程知識庫 MCP 伺服器：讓 Claude Desktop 等 MCP 客戶端，能呼叫工具查詢補習班的課程文件。

只用 Python 標準函式庫（3.9 以上），自行實作 MCP 的 stdio 傳輸與 JSON-RPC 2.0 訊息，不依賴官方 SDK。

提供 3 個工具：
  list_documents       列出知識庫有哪些文件
  search_course_docs   用關鍵字（BM25＋同義詞擴充）搜尋最相關的段落，附段落編號
  get_document         讀取整份文件

通訊方式（stdio）：
  客戶端啟動這支程式，透過 stdin 送出一行一個 JSON-RPC 訊息，伺服器從 stdout 一行一個回應。
  stdout 只能輸出協定訊息；所有紀錄一律寫到 stderr，否則會打亂通訊。

單獨執行 `python server.py` 會停在等待輸入的狀態，這是正常的：它在等 MCP 客戶端送訊息。
"""
import json, os, sys, traceback

from kb_search import KnowledgeBase

SERVER_INFO = {"name": "course-kb", "version": "1.0.0"}
DEFAULT_PROTOCOL = "2025-06-18"

KB = KnowledgeBase(os.path.join(os.path.dirname(os.path.abspath(__file__)), "knowledge_base"))

TOOLS = [
    {
        "name": "list_documents",
        "description": "列出補習班知識庫中的所有文件與各文件的段落標題。不確定該查哪份文件時先呼叫這個。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "search_course_docs",
        "description": ("搜尋補習班的課程、價目、退費、上課方式、程度檢測、獎學金、分校等規定，"
                        "回傳最相關的段落與段落編號。回答學員問題前應先呼叫，並只根據回傳內容回答、註明段落編號；"
                        "沒有相關段落時要說資料中找不到。"),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "學員的問題或關鍵字，例如「開課後退費」"},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 8, "default": 4, "description": "回傳段落數"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_document",
        "description": "讀取一整份文件的完整內容。需要看完整規定（例如退費的所有條件）時使用。",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string", "enum": KB.document_names(), "description": "文件名稱"}},
            "required": ["name"],
        },
    },
]


def log(*args):
    print("[course-kb]", *args, file=sys.stderr, flush=True)


# ---------- 工具實作 ----------
def tool_list_documents(_args):
    lines = []
    for name, title, headings in KB.outline():
        lines.append(f"- {name}：{title}（{'、'.join(headings)}）")
    return "知識庫文件：\n" + "\n".join(lines)


def tool_search(args):
    query = str(args.get("query", "")).strip()
    if not query:
        raise ValueError("query 不可以是空的")
    top_k = int(args.get("top_k", 4))
    if not 1 <= top_k <= 8:
        raise ValueError("top_k 要介於 1 到 8")
    hits = KB.search(query, top_k)
    if not hits:
        return f"知識庫中找不到和「{query}」相關的段落。請告訴學員資料中沒有這項資訊，建議洽詢顧問。"
    parts = [f"[{h['id']}]（相關分數 {h['score']}）\n{h['text']}" for h in hits]
    return f"找到 {len(hits)} 個相關段落。回答時只能根據以下內容，並註明段落編號：\n\n" + "\n\n".join(parts)


def tool_get_document(args):
    name = str(args.get("name", ""))
    if name not in KB.document_names():
        raise ValueError(f"沒有「{name}」這份文件，可用的有：{', '.join(KB.document_names())}")
    return KB.document_text(name)


HANDLERS = {"list_documents": tool_list_documents, "search_course_docs": tool_search, "get_document": tool_get_document}


# ---------- JSON-RPC ----------
def result(msg_id, res):
    return {"jsonrpc": "2.0", "id": msg_id, "result": res}


def error(msg_id, code, message):
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def handle(msg):
    """處理一則訊息；通知（沒有 id）不回應，回傳 None。"""
    method, msg_id, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    is_notification = "id" not in msg

    if method == "initialize":
        version = params.get("protocolVersion") or DEFAULT_PROTOCOL   # 沿用客戶端提出的協定版本
        log("initialize from", params.get("clientInfo", {}).get("name", "?"), "protocol", version)
        return result(msg_id, {"protocolVersion": version,
                               "capabilities": {"tools": {"listChanged": False}},
                               "serverInfo": SERVER_INFO,
                               "instructions": "查詢補習班規定時先用 search_course_docs，只根據回傳段落回答並註明段落編號。"})
    if method == "notifications/initialized" or (is_notification and method and method.startswith("notifications/")):
        return None
    if method == "ping":
        return result(msg_id, {})
    if method == "tools/list":
        return result(msg_id, {"tools": TOOLS})
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in HANDLERS:
            return error(msg_id, -32602, f"未知的工具：{name}")
        log("tools/call", name, json.dumps(args, ensure_ascii=False))
        try:
            text = HANDLERS[name](args)
            return result(msg_id, {"content": [{"type": "text", "text": text}], "isError": False})
        except ValueError as e:   # 參數問題：以工具錯誤回傳，讓模型看得到原因並修正
            return result(msg_id, {"content": [{"type": "text", "text": f"錯誤：{e}"}], "isError": True})
    if is_notification:
        return None
    return error(msg_id, -32601, f"不支援的方法：{method}")


def main():
    log("server started, documents:", ", ".join(KB.document_names()))
    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer   # 用位元組讀寫，避免 Windows 主控台編碼把中文弄亂
    for raw in stdin:
        line = raw.decode("utf-8").strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            reply = error(None, -32700, "JSON 格式錯誤")
        else:
            try:
                reply = handle(msg)
            except Exception as e:   # 不讓單一錯誤讓伺服器整個停掉
                log(traceback.format_exc())
                reply = error(msg.get("id"), -32603, f"伺服器內部錯誤：{e}")
        if reply is not None:
            stdout.write((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))
            stdout.flush()


if __name__ == "__main__":
    main()
