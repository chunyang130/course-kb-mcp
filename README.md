# 課程知識庫 MCP 伺服器

> A Model Context Protocol (MCP) server that lets Claude Desktop search a course knowledge base. The stdio transport and JSON-RPC 2.0 messages are implemented directly with the Python standard library (no SDK), with an automated test that plays the client role.

把補習班的課程文件做成 MCP 伺服器。接上 Claude Desktop 之後，在對話裡問「開課後兩週可以退多少」，Claude 會自己呼叫這個伺服器的工具查文件，再根據查到的段落回答並註明出處。

MCP（Model Context Protocol）是讓 AI 連接外部工具與資料的標準。這個專案沒有使用官方 SDK，而是直接用 Python 標準函式庫實作協定，目的是弄清楚它底層的運作：客戶端送什麼訊息、伺服器要回什麼。
知識庫與檢索方法沿用 [course-qa-rag](https://github.com/chunyang130/course-qa-rag)（BM25＋同義詞擴充），資料全部虛構。

## 架構

```
Claude Desktop（MCP 客戶端）
   │  啟動 python server.py，透過 stdin／stdout 傳 JSON-RPC 訊息
   ▼
server.py（MCP 伺服器）── 處理 initialize、tools/list、tools/call
   │
   ▼
kb_search.py ── 載入 knowledge_base/ 的文件，切段、BM25 檢索
```

## 提供的工具

| 工具 | 用途 | 參數 |
| --- | --- | --- |
| `list_documents` | 列出所有文件與段落標題 | 無 |
| `search_course_docs` | 搜尋最相關的段落，附段落編號與原文 | `query`、`top_k`（1–8，預設 4） |
| `get_document` | 讀取整份文件 | `name`（限定為現有文件名稱） |

工具說明（description）本身也是設計的一部分：裡面寫明「只根據回傳內容回答、註明段落編號、找不到就說找不到」，Claude 會依照工具說明決定何時呼叫、怎麼使用結果。

## 協定流程

一行一則 JSON 訊息，經由 stdin／stdout 傳遞：

```
客戶端 → {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18",...}}
伺服器 ← {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18","capabilities":{"tools":{...}},"serverInfo":{...}}}
客戶端 → {"jsonrpc":"2.0","method":"notifications/initialized"}          （通知，不回應）
客戶端 → {"jsonrpc":"2.0","id":2,"method":"tools/list"}
伺服器 ← {"jsonrpc":"2.0","id":2,"result":{"tools":[...3 個工具...]}}
客戶端 → {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"search_course_docs","arguments":{"query":"退費"}}}
伺服器 ← {"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"找到 4 個相關段落..."}],"isError":false}}
```

## 實作時的重點

| 重點 | 做法 |
| --- | --- |
| stdout 只能放協定訊息 | 所有紀錄寫到 stderr；stdout 混入任何其他文字，客戶端就無法解析 |
| Windows 中文編碼 | 以位元組讀寫 stdin／stdout，固定用 UTF-8，不受主控台編碼影響 |
| 兩種錯誤分開處理 | 參數錯誤（例如空白查詢）用 `isError: true` 回傳，讓模型看得到原因並自行修正；未知工具、不支援的方法用 JSON-RPC 錯誤碼（-32602、-32601） |
| 伺服器不能因單一錯誤中斷 | 格式錯誤的訊息回 -32700，其他例外回 -32603，之後繼續處理下一則 |
| 參數限定範圍 | `get_document` 的文件名稱用 enum 列出，`top_k` 限定 1–8 |

## 測試

`test_server.py` 扮演 MCP 客戶端，啟動伺服器後送出 18 項檢查：

```
python test_server.py
```

```
✓ initialize 回傳相同的協定版本
✓ tools/list 有 3 個工具
✓ 搜尋退費 → 第一段是 refund#2
✓ 同義詞擴充：錯過 → 找到缺課補課段落
✓ 知識庫沒有的內容 → 回傳找不到
✓ 空白查詢 → isError=true 並說明原因
✓ 格式錯誤的訊息 → -32700，伺服器不中斷
...
18 項通過，0 項失敗
```

## 實際運作驗證

已在 Windows 上的 Claude Desktop 實際接上並使用：

- 在 Claude Desktop 對話中詢問開課後的退費規定，Claude 自行呼叫 `search_course_docs` 查詢，並依回傳段落回答
- 再由另一個 Claude 對話透過同一台電腦呼叫工具，查詢「錯過一堂課怎麼補？」，回傳結果：

```
找到 2 個相關段落。回答時只能根據以下內容，並註明段落編號：

[class_modes#1]（相關分數 3.27）
上課方式－面授
在分校教室上課，可當場發問。缺課可預約該堂錄影補課，每期最多 3 次。
```

同義詞擴充（錯過→缺課）在真實環境中正常運作，正確段落排在第 1 名。

## 接上 Claude Desktop

**自動設定（建議）**：先完全關閉 Claude Desktop，再執行

```
python install_claude_desktop.py
```

程式會先備份設定檔，只加入 `course-kb` 這一筆，其他設定一律保留，並自動帶入這台電腦上 Python 與 `server.py` 的實際路徑。

**手動設定（Windows）**

1. 在 PowerShell 執行 `where python`，記下 python.exe 的完整路徑
2. 打開 Claude Desktop →「設定」（Settings）→「開發者」（Developer）→「編輯設定」（Edit Config），會開啟 `claude_desktop_config.json`
3. 加入以下內容（路徑換成你自己的，反斜線要寫兩次）：

```json
{
  "mcpServers": {
    "course-kb": {
      "command": "C:\\Users\\你的使用者名稱\\AppData\\Local\\Programs\\Python\\Python313\\python.exe",
      "args": ["C:\\Users\\你的使用者名稱\\Downloads\\course-kb-mcp\\server.py"]
    }
  }
}
```

4. 完全關閉 Claude Desktop（包括右下角系統匣的圖示）再重新打開
5. 在對話中問：「用 course-kb 查一下，開課後兩週想退費可以退多少？」

macOS 的設定檔在 `~/Library/Application Support/Claude/claude_desktop_config.json`，`command` 改成 `python3`。

## 檔案說明

| 檔案 | 內容 |
| --- | --- |
| `server.py` | MCP 伺服器：stdio 傳輸、JSON-RPC 處理、3 個工具 |
| `kb_search.py` | 知識庫載入、切段、BM25＋同義詞檢索 |
| `test_server.py` | 扮演客戶端的自動測試（18 項） |
| `install_claude_desktop.py` | 自動把伺服器加進 Claude Desktop 設定檔（先備份、只改這一筆） |
| `knowledge_base/` | 8 份虛構的補習班文件 |

## 學到的事

- MCP 的核心很單純：一個講好格式的對話。客戶端問「你有哪些工具」，伺服器回工具清單和參數格式；客戶端說「呼叫這個工具」，伺服器回結果
- 工具說明寫得好不好，直接影響 AI 會不會在對的時機呼叫、會不會照結果回答
- 錯誤要分成「給模型看的」和「給程式看的」：參數錯誤讓模型知道原因並重試，協定錯誤才用錯誤碼
- 在我的 RAG 專案裡，是我的程式決定什麼時候檢索；接上 MCP 後，改由 Claude 自己判斷什麼時候要查資料
