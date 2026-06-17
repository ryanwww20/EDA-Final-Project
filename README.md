# EDA Final Project — ICCAD 2026 Contest Problem A

**LLM 輔助 Netlist 探索與轉換**

> Cadence Design Systems, Inc. — Chung-Han Chou, Hung-Chun Chiu, Chih-Jen (Jacky) Hsu, and Yong Liu

---

## 概述

這個專題是 **ICCAD 2026 Contest Problem A** 的實作。目標是建立一個系統，接受**自然語言請求**，並使用由雲端 LLM agent 驅動的自定義 EDA engine，對 gate-level Verilog netlist 執行對應的 **EDA 分析或轉換**。

大致流程：使用者用白話文描述需求（「從 input A 到 output B 的最大 logic depth 是多少？」、「插入 buffer 讓每個 gate 的 fanout 不超過 4」），系統將其轉換為結構化的 EDA 操作，在當前 netlist 上執行，並自動回傳清楚的答案。

---

## 問題定義

傳統 EDA 流程中，工程師必須熟記確切的工具指令、參數格式以及多步驟流程，才能探索或轉換設計。LLM 可以降低這個門檻，但它本身對工具的內部介面毫無所知。挑戰在於：

1. **定義**清楚的 EDA 操作介面（「EDA backend」）
2. **實作** backend：分析查詢 + 結構轉換
3. **以 LLM agent 驅動** backend，將自然語言轉換為結構化 EDA 操作
4. **驗證**轉換後的設計維持 functional equivalence

參賽者必須自行建立這三層：EDA 工具、操作目錄（operation catalog），以及 LLM 整合。

---

## 系統架構

```
stdin（自然語言請求，每行一條）
          │
          ▼
       main.py          ← I/O 迴圈、狀態管理、LLM API 呼叫
          │
          ├─ keyword router（快速 fallback）
          │
          └─ LLM planner  ← 將請求 + 設計摘要送給雲端 LLM
                │             接收 JSON plan
                ▼
         llm_planner.py  ← operation catalog、plan validator、dispatcher
                │
                ├─ tools/analysis_fanin_fanout.py  ← cone / fanin / fanout 查詢
                ├─ tools/analysis_logic.py          ← BDD-based formal analysis
                ├─ tools/analysis_netlist_stats.py  ← gate / netlist 統計查詢
                └─ netlist_twoside.py               ← Verilog 解析 / 輸出 / IR

stdout: #RESPONSE <id> ... #END <id>（每次回應後 flush）
log:    <case_name>.log（stdout 回應的鏡像）
```

### 核心設計原則

- **LLM 負責規劃，backend 負責執行。** LLM 看到結構化的 operation catalog，回傳 JSON plan，它不寫 Python；backend 執行確定性的函式。
- **分層架構。** `algorithm/` 存放領域無關的演算法（DFS、BDD）。`tools/` 存放 EDA 專用邏輯。`main.py` 只處理 I/O。
- **循序狀態。** 每個 testcase 中的請求都在當前設計狀態下執行，並累積所有先前的轉換結果。

---

## I/O 規格

執行方式：

```
./cada0001_alpha -config <config_file_path>
```

**Input（stdin）：** 每行一條自然語言請求。grader 在收到 `#END <id>` 後才傳送下一行。

**Output（stdout）：**
```
#RESPONSE 1
<自然語言回答>
#END 1

#RESPONSE 2
<自然語言回答>
#END 2
```

**Log 檔：** 每條回應同步寫入 `<case_name>.log`（testcase 名稱會在每個 testcase 的第一條請求中宣告）。

**時間限制：**
- 基本操作（load/write design、begin testcase）：**60 秒**
- 其他所有操作：**300 秒**

---

## Netlist 格式

輸入為**平坦 gate-level Verilog netlist**（單一 module，無階層）。

支援的元素：
- **Primitive gate：** `and`、`or`、`nand`、`nor`、`xor`、`xnor`、`not`、`buf`
  - 除 `not` 和 `buf` 為單輸入外，其餘均為 2-input
- **Flip-flop：** `dff`，帶有具名 port：`.RN`、`.SN`、`.CK`、`.D`、`.Q`
- **常數：** `1'b0`、`1'b1`
- **Bus：** scalar 與 bus 訊號（例如 `input [31:0] a`，展開為 `a[0]`...`a[31]`）

DFF instance 是**循序邊界**——combinational analysis 不穿越 DFF。DFF 的 `.Q` 視為 source（等同 PI），`.D` 視同 sink（等同 PO）。

---

## 任務類別

### 4.1 基本操作
載入與輸出設計。是每個 testcase 的基礎。

| 請求範例 | 操作 |
|---|---|
| "Load test1.v from directory design/." | `load_design` |
| "Write out the current design to result.v." | `write_design` |
| "This is the beginning of testcase case23. Please output a copy of the log into case23.log." | `begin_testcase` |

### 4.2 分析任務
對當前 netlist 結構或功能的唯讀查詢。

**Gate / Netlist 統計：**
- 依類型統計 gate 數量（AND、OR、NAND、NOR、NOT、BUF、XOR、XNOR、DFF）
- 回報總 gate 數、PI/PO 數量、bus 寬度
- 列出特定類型的 gate 及其 pin 連接

**Fanin / Fanout / Cone 分析：**
- 某個 gate 或訊號的直接 fanin / fanout
- 遞移 fanin cone / fanout cone
- 兩個 output 之間的 shared fanin cone
- fanout 最高的訊號或 primary input
- 所有 primary output 中最深 / 最大的 fanin cone

**Path 分析：**
- 從 A 到 B 是否存在 combinational path（可選擇避開節點 C）
- 列舉兩個節點之間的所有 path
- 從 input 到 output 的最大 logic depth
- 全設計中最長 / critical combinational path depth
- 是否所有 path 都經過某個節點
- 全設計最大 depth（PI→PO、PI→DFF D、register-to-register）

**Logic / Formal 分析（BDD-based）：**
- 兩個訊號是否 functionally equivalent？
- 某個 output 是否恆為常數 0 或 1？
- 某個 output 是否依賴某個 input？
- 推導 output 相對於 primary input 的 Boolean equation
- 檢查某個節點的函式對兩個 input 是否對稱
- 找出一對 (a, b) 使得 NAND(a, b) ≡ target signal

**Sequential / DFF 分析：**
- 列出由特定 clock net 驅動的所有 flip-flop
- 分析 D-pin logic 的 enable/hold 結構

**結構健康檢查：**
- 找出 input 接常數的 gate（tied high/low）
- 偵測 dangling gate（未連接到任何 primary output）
- 偵測多餘或浮接節點

**Equivalence 驗證**（轉換後）：
- 驗證當前設計與原始載入的 netlist functionally equivalent
- 驗證當前設計與上一次轉換前的狀態 equivalent

### 4.3 轉換與最佳化任務
對 netlist 的結構修改。除非明確說明，所有轉換必須維持 functional equivalence。

**Fanout / Buffer 插入：**
- 插入 buffer 使每個 gate 的 fanout 不超過 N
- 對特定高 fanout 訊號的每個負載各插一個 buffer

**Depth / Timing 最佳化：**
- 透過 logic restructuring 降低 critical path depth
- 最佳化特定 output 的 fanin cone，使其深度 ≤ N level
- 最小化全設計的最大 path depth

**清理 / 簡化：**
- 移除不影響任何 primary output 的 dangling gate 與 net
- 合併相鄰的反相器對（NOT→NOT）為直接連線
- 合併 functionally equivalent 的 gate 對
- 移除多餘 / 浮接節點
- Constant propagation（簡化有常數 input 的 gate）

**重命名 / 重接線：**
- 重命名 wire 並更新 netlist 中所有引用
- 重命名 gate instance
- 將 gate input pin 重接到不同訊號

**Technology / Logic Remapping：**
- 將所有 XNOR gate 替換為等效的 NOR-only 實作
- 將所有 XOR gate 替換為等效的 NAND-only 實作（每個 XOR 用 4 個 NAND）
- 以 AND + NOT gate 重建整個 netlist
- 將 netlist remap 為只使用 NAND + NOT gate
- 將某個 cone 中的 OR gate 替換為 NAND + NOT 等效
- 將某個 cone 中的 XOR gate 分解為 AND / OR / NOT

---

## 專案結構

```
EDA-Final-Project/
│
├── main.py                      # 主要 I/O 迴圈與協調器
├── netlist_twoside.py           # Verilog parser、Netlist/Gate IR、輸出
│
├── algorithm/
│   ├── graph_traversal.py       # 領域無關的 DFS/BFS
│   └── boolean_logic.py         # BoolExpr、BDDManager、gate_expr
│
├── tools/
│   ├── llm_planner.py           # Operation catalog、JSON plan executor、system prompt
│   ├── analysis_fanin_fanout.py # Fanin/fanout/cone 分析（已實作）
│   ├── analysis_logic.py        # BDD-based formal analysis（已實作）
│   └── analysis_netlist_stats.py # gate / netlist 統計查詢（已接線）
│
├── docs/
│   ├── EDA_tools.md             # 所有 testcase 的完整工具清單
│   ├── EDA_backend_architecture.md  # 架構與擴展模式
│   └── netlist_structure_design.md  # Netlist IR 設計筆記
│
├── testcase/
│   ├── test01/ … test40/        # 40 個測試案例（prompt.txt + testXX.v）
│
├── test_fanin_fanout.py         # fanin/fanout 分析的 smoke test
├── test_logic_analysis.py       # logic/formal 分析的 smoke test
├── simple.v / sample.v          # 用於本地測試的小型 netlist
│
├── A_20260212.pdf               # 官方競賽題目說明
└── config_openai.yml            # LLM 設定（OpenAI/Anthropic）
```

---

## LLM 設定

系統透過啟動時傳入的 config 檔連接雲端 LLM。評測環境使用：
- **OpenAI：** `gpt-4o-mini`
- **Anthropic：** `claude-haiku-4-5`

Config 檔格式：
```yaml
provider: "openai"  # 或 "anthropic"

openai:
  api_key: <YOUR_API_KEY>
  model: "gpt-4o-mini"

anthropic:
  api_key: <YOUR_API_KEY>
  model: "claude-haiku-4-5"

generation:
  temperature: 0.2
  max_output_tokens: 4096
```

LLM 接收包含完整 operation catalog 的 system prompt，並回傳如下的 JSON plan：
```json
{
  "operations": [
    {"op": "load_design", "args": {"path": "testcase/test08/test08.v"}},
    {"op": "max_logic_depth", "args": {"src": "in0", "dst": "out3"}}
  ]
}
```

---

## 當前實作狀態

### 已實作
| 層次 | 狀態 |
|---|---|
| Netlist 解析 / 輸出（round-trip safe） | 完成 |
| Gate-level IR（`Netlist`、`Gate`） | 完成 |
| Fanin/fanout/cone 分析 | 完成 |
| BDD-based logic/formal 分析 | 完成 |
| 各類型 gate 計數 | 完成（待整合進 LLM catalog） |
| LLM API 整合（OpenAI + Anthropic） | 完成 |
| JSON plan executor + operation catalog | 完成 |
| I/O 迴圈、log 檔、狀態管理 | 完成 |

### 尚未實作
| 功能 | 需要的 testcase |
|---|---|
| Path existence（含 avoid-node） | test06, 10, 20 |
| Path enumeration | test08, 10, 20 |
| 最大 / critical logic depth 查詢 | test04, 10, 11, 13, 20, 35 |
| Gate info / 依類型列出 gate | test31, 35, 39, 40 |
| DFF / clock 查詢 | test35, 36 |
| Buffer insertion（fanout 限制） | test21, 24, 26, 30, 31, 34 |
| Wire / gate 重命名 | test25, 35 |
| Dead / dangling gate 移除 | test23, 30, 32, 33 |
| Back-to-back inverter collapse | test26, 30, 35 |
| Technology remapping（XOR→NAND、XNOR→NOR、AND+NOT only） | test25–35, 39, 40 |
| Depth 最佳化 | test22, 25–28, 30, 33, 35, 40 |
| Functional equivalence 驗證（對比原始 / 轉換前 snapshot） | test31–40 |
| Constant propagation | test32, 36, 38, 39 |
| 合併 functionally equivalent / 結構重複 gate | test29, 33 |

---

## 評分

- **每個 testcase = 1 分。** 最終分數 = 40 個 testcase 總和。
- **分析題：** 答案正確才得分。
- **轉換題：** 所有硬性要求必須滿足（不得有非預期的功能改變、結構限制如 max fanout ≤ N）。違反任何硬性要求該 testcase 得 0 分。
- **最佳化題：** 依 `cost_min / cost` 比例排名（cost 越低排名越高）。

---

## 執行方式

```bash
# 對單一 testcase 互動執行
python3 main.py -config config_openai.yml < testcase/test01/prompt.txt

# 執行 smoke test
python3 test_fanin_fanout.py
python3 test_logic_analysis.py

# 驗證 netlist round-trip
python3 netlist_twoside.py testcase/test01/test01.v /tmp/out.v
```

---

## 新增 Backend 操作的步驟

參照 `tools/analysis_fanin_fanout.py` 建立的 module 模式：

1. 在 `algorithm/` 實作純函式（若為通用演算法），或直接放在 `tools/` module 中。
2. 在 module 的 `OP_TABLE` 新增一筆，包含 `func`、`required_args`、`category`、`public`、`description`。
3. 透過 `get_public_op_catalog()` 匯出，讓 LLM 看得到這個操作。
4. 實作 `dispatch_xxx_op()` 與 `format_xxx_result()`。
5. 將新 module 接進 `tools/llm_planner.py`（`_implemented_tables()`）以及 `main.py`（`handle_analysis` 或 `handle_transform`）。
6. 新增 smoke test。
