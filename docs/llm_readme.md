# LLM Pipeline 使用說明（新版）

本文件依照 `docs/llm_pipeline.md` 更新，說明新版 LLM orchestration 流程與各檔案責任。

核心原則：

1. LLM 不直接執行 Python。
2. LLM 先產生高階 `plan.md`，再透過迴圈逐步產生 `operation.json`。
3. 所有實際執行都由 backend 負責，執行結果只寫入 `history.json`。

## 新版流程總覽

```text
prompt + system context + skill.md + tool.md
  -> LLM
  -> plan.md

plan.md + current-plan.md + history.json + skill.md + tool.md
  -> LLM
  -> operation.json
  -> backend validate + execute
  -> output
  -> program append history.json
  -> LLM update current-plan.md
  -> next operation.json (loop)
```

簡化成一句話：

```text
plan -> operation -> output -> history -> update plan -> next operation
```

## 快速執行（單次跑完整 testcase）

在專案根目錄直接執行：

```bash
python3 main.py < testcase/test10/prompt.txt
```

這個用法會讓 `main.py` 依序讀取 `prompt.txt` 的每一行請求，並在同一次執行中輸出多個 `#RESPONSE ... #END` 區塊。

執行後可在以下位置查看結果：

- log：`output/log/test10.log`
- 輸出 Verilog：`output/out_v/test10_out.v`

## 各檔案責任

- `prompt.txt`: 原始使用者需求（task data，不是 trusted system instruction）。
- `skill.md`: LLM 的推理/拆解策略。
- `tool.md`: 人類可讀的工具目錄，協助 LLM 選 operation。
- `plan.md`: 第一次 LLM 呼叫產生的高階計畫，不直接執行。
- `current-plan.md`: 每輪由 LLM 更新的進度狀態（已完成、待完成、下一步）。
- `operation.json`: LLM 產生的具體指令，必須經 backend 驗證後才可執行。
- `history.json`: 只能由程式寫入，記錄每次 operation 的真實執行結果。

## `operation.json` 格式

主要建議沿用現有執行介面：

```json
{
  "operations": [
    {
      "op": "count_gates_of_type",
      "args": {
        "type": "NAND"
      }
    }
  ]
}
```

也可接受單一 operation shorthand（由 backend 正規化）：

```json
{
  "op": "count_gates_of_type",
  "args": {
    "type": "NAND"
  }
}
```

backend 必須做：

- JSON parse
- operation 名稱與參數驗證
- 拒絕未知 operation
- 只呼叫已註冊 backend 函式

## `history.json` 格式

成功範例：

```json
[
  {
    "step": 1,
    "operation": {
      "op": "count_gates_of_type",
      "args": {
        "type": "NAND"
      }
    },
    "status": "success",
    "payload": {
      "type": "NAND",
      "count": 42
    },
    "text": "The design contains 42 NAND gates."
  }
]
```

失敗範例（失敗也要寫入）：

```json
[
  {
    "step": 2,
    "operation": {
      "op": "get_gate_info",
      "args": {
        "gate": "U999"
      }
    },
    "status": "error",
    "error": "Unknown gate: U999"
  }
]
```

## 建議執行迴圈

```text
1. 讀 prompt.txt / skill.md / tool.md
2. LLM 產生 plan.md
3. 初始化 current-plan.md = plan.md
4. 初始化 history.json = []
5. 重複：
   a. LLM 讀 current-plan.md + history.json 產生 operation.json
   b. backend validate + execute operation.json
   c. 程式 append history.json
   d. LLM 更新 current-plan.md
   e. 若完成則停止
6. 輸出最終結果
```

## 停止條件

任一條件成立即可停止：

- `current-plan.md` 包含 `Status: complete`
- LLM 輸出特別 operation（例如 `final_answer`）
- 達到 `max_iterations`
- 連續錯誤超過門檻

建議初始設定：

```yaml
llm:
  pipeline_mode: true
  max_pipeline_iterations: 10
```

## 與現有程式的關係

新版是「外層 orchestration loop」升級，不是重寫 backend：

- 保留 `tools/llm_planner.py` 的 operation catalog / validator / dispatcher。
- 保留 `execute_plan(state, raw_plan)` 作為執行邊界。
- 主要新增 `plan.md`、`current-plan.md`、`history.json` 三者之間的 LLM 迴圈。

## Pipeline 狀態檔案位置

建議每個 testcase 使用獨立狀態目錄：

```text
testcase/<case_name>/llm_state/
  ├─ plan.md
  ├─ current-plan.md
  ├─ operation.json
  └─ history.json
```

## Debug 建議

建議每輪記錄：

- `plan.md` / `current-plan.md` / `operation.json` / `history.json` 寫入位置
- 本輪執行 operation 名稱與參數
- loop 停止原因（complete / max iterations / error threshold）

這樣可快速區分問題在：

- LLM 規劃（plan/update）
- operation 產生
- backend 驗證
- backend 執行結果
