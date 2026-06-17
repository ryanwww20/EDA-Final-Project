# EDA Backend Architecture

這份文件說明目前 EDA backend 的架構、資料流、tool module pattern，以及它和 LLM layer 之間的串接方式。

核心原則：LLM layer 不直接面對一百多個細粒度 EDA tool。Backend 提供穩定的 dispatcher / catalog，LLM layer 只需要產生 structured request，再由 backend 執行。

---

## Current Data Flow

目前執行流程如下：

```text
stdin prompt
  |
  v
main.py
  |
  +-- handle_begin()
  +-- handle_load()  -> netlist_twoside.parse()
  +-- handle_write() -> netlist_twoside.dump()
  +-- handle_analysis()
  |     |
  |     +-- tools.analysis_fanin_fanout
  |     +-- tools.analysis_logic
  |
  +-- handle_transform()  # TODO
  |
  v
stdout response block + testcase log
```

現在 `main.py` 是 I/O orchestrator。它不放真正的 EDA 演算法，只處理：

- 保存目前 testcase state。
- load / write design。
- 根據 request 類型呼叫對應 tool module。
- 把結果包成 grader 需要的文字輸出。

---

## Important Files

| File | Responsibility |
| --- | --- |
| `main.py` | Grader I/O loop、state 管理、routing |
| `netlist_twoside.py` | Verilog parser、Netlist / Gate IR、dump |
| `algorithm/graph_traversal.py` | 通用 BFS / DFS |
| `algorithm/boolean_logic.py` | 通用 Boolean expression / ROBDD 演算法 |
| `tools/analysis_fanin_fanout.py` | 1.2 fanin / fanout / cone analysis |
| `tools/analysis_logic.py` | 1.4 functional / logic / formal analysis |
| `tools/count_gate.py` | 早期 gate count utility，之後建議整合到 Netlist IR |
| `docs/EDA_tools.md` | 所有需求 tool 的完整列表 |
| `docs/netlist_structure_design.md` | Netlist IR 設計說明 |
| `test_fanin_fanout.py` | fanin/fanout smoke test |
| `test_logic_analysis.py` | logic/formal smoke test |

---

## Netlist IR

Backend 的共同資料結構是 `netlist_twoside.Netlist`。

```python
class Netlist:
    module: str
    port_order: list[str]
    inputs: set[str]
    outputs: set[str]
    bus_width: dict[str, tuple[int, int]]
    gates: dict[str, Gate]
    driver: dict[str, str]
    fanout: dict[str, list[str]]
```

```python
class Gate:
    name: str
    type: str
    out: str
    ins: list[str]
    ports: dict[str, str]
```

設計重點：

- Net-centric：以 net 為中心查 driver / fanout。
- Primitive gate 的 output 是第一個 positional argument。
- Bus 會展開成 bit-level net，例如 `n0[3]`。
- Constant `1'b0` / `1'b1` 不當成普通 net。
- DFF 是 sequential boundary。Combinational analysis 不要穿過 DFF。

注意：部分 testcase 可能有 multiple drivers。現有 `netlist.driver` 會保留最後一個 driver，而 `analysis_fanin_fanout.build_fanin_fanout_index()` 目前會對 multiple driver 報錯。後續若要完整支援所有 testcase，要明確決定 multiple-driver policy。

---

## Tool Module Pattern

新增 analysis tool 時，module 結構維持和 `tools/analysis_fanin_fanout.py`、`tools/analysis_logic.py` 一致。

每個 tool module 建議包含：

```text
1. IR adapter helpers
2. Pure query functions
3. OP_TABLE
4. PUBLIC_OP_TABLE
5. get_public_op_catalog()
6. dispatch_xxx_op()
7. format_xxx_result()
8. try_parse_xxx_request()
```

例如：

```python
OP_TABLE = {
    "signals_equivalent": {
        "func": lambda nl, a: signals_equivalent(nl, a["sig_a"], a["sig_b"]),
        "required_args": ("sig_a", "sig_b"),
        "category": "logic_formal",
        "public": True,
        "description": "Check whether two signals are functionally equivalent.",
    },
}
```

為什麼要這樣切：

- Pure function 可以直接單元測試。
- `OP_TABLE` 給 LLM / dispatcher 看。
- `format_xxx_result()` 集中控制輸出文字。
- `try_parse_xxx_request()` 是目前 rule-based fallback，之後可以被 LLM 取代或輔助。

---

## Algorithm Layer

`algorithm/` 只放 domain-independent 演算法。

可以放：

- BFS / DFS
- topological traversal
- longest path DP
- Boolean expression simplification
- BDD / SAT helper
- graph articulation point

不放：

- prompt regex
- `Netlist` / `Gate` 直接操作邏輯
- grader output formatting
- testcase-specific workaround

正確分層範例：

```text
algorithm.boolean_logic
  - BoolExpr
  - BDDManager
  - bdd_equivalent()

tools.analysis_logic
  - 把 Netlist gate 轉成 BoolExpr
  - 呼叫 bdd_equivalent()
  - 回傳 EDA tool 結果
```

這樣之後如果換成 Z3 / PyEDA / C++ backend，tool API 不需要大改。

---

## LLM Integration Contract

LLM layer 和 backend 的邊界是 structured request。LLM layer 可以參考 backend catalog，但不需要知道每個 operation 的內部演算法。

建議採用兩層決策：

```text
Natural language prompt
  |
  v
Split into atomic tasks
  |
  v
Classify each task into coarse category
  |
  v
Generate structured request
  |
  v
Backend dispatcher
```

LLM-visible category 可以維持粗粒度：

| Category | Backend module |
| --- | --- |
| `design_io` | `main.py` load/write |
| `netlist_stats` | future `tools.analysis_stats` |
| `graph_query` | `tools.analysis_fanin_fanout` |
| `path_depth_query` | future `tools.analysis_path` |
| `logic_formal_query` | `tools.analysis_logic` |
| `sequential_query` | future `tools.analysis_sequential` |
| `structural_health` | future `tools.analysis_health` |
| `transform` | future transformation modules |
| `verification` | future equivalence verification module |

LLM layer 輸出的 structured request 格式：

```json
{
  "category": "logic_formal_query",
  "op": "signals_equivalent",
  "args": {
    "sig_a": "n2122",
    "sig_b": "n2116"
  }
}
```

或：

```json
{
  "category": "graph_query",
  "op": "transitive_fanin_cone",
  "args": {
    "target": "n3"
  }
}
```

Backend module 透過 `get_public_op_catalog()` 提供可用 operation metadata。LLM layer 可以把 catalog 放進 prompt 或 tool schema，而不是手寫同步兩份清單。

---

## Handling Long Prompts

test31 之後常常一個 prompt 有很多要求。Backend 比較適合處理 atomic task；長 prompt 應先拆成多個 structured request，再依序 dispatch。

建議 pipeline：

```text
Prompt:
  "Check equivalence. Rename wire. Count BUF gates. Write output."

Atomic tasks:
  1. verify_equivalent_to_original()
  2. rename_wire(old, new)
  3. count_added_buffers()
  4. write_design(path)
```

每個 atomic task 各自產生 structured request，依序送進 backend。Transformation 後的 state 會留在 `State.netlist`。

---

## Current Implemented Analysis

### 1.2 Fanin / Fanout / Cone

Module: `tools/analysis_fanin_fanout.py`

已實作：

- `immediate_fanin_gates`
- `immediate_fanout_gates`
- `transitive_fanin_cone`
- `transitive_fanout_cone`
- `count_fanin_cone_gates`
- `count_fanout_cone_gates`
- `shared_fanin_cone_gates`
- `highest_fanout_signal`
- `highest_fanout_primary_input`
- `largest_fanin_cone_output`

測試：

```bash
python3 test_fanin_fanout.py
```

### 1.4 Functional / Logic / Formal

Module: `tools/analysis_logic.py`

Algorithm: `algorithm/boolean_logic.py`

已實作 plain Python 版本：

- `signals_equivalent`
- `output_always_constant`
- `output_depends_on_input`
- `derive_boolean_equation`
- `write_logic_expression`
- `boolean_function_of_output`
- `function_symmetric`
- `exists_nand_pair_equivalent_to`

測試：

```bash
python3 test_logic_analysis.py
```

目前 1.4 使用 ROBDD，不依賴外部 solver。DFF Q / unknown driver 會視為 symbolic variable。

---

## Analysis Extension Pattern

假設新增 1.3 path analysis，檔案與資料流會長成：

1. `algorithm/path_analysis.py` 放通用 path / depth 演算法。
2. `tools/analysis_path.py` 放 Netlist adapter、OP_TABLE、dispatcher、formatter。
3. Pure query function 範例：

```python
def path_exists(netlist, src, dst, avoid=None) -> bool:
    ...
```

4. 加到 `OP_TABLE`：

```python
"path_exists": {
    "func": lambda nl, a: path_exists(nl, a["src"], a["dst"], a.get("avoid")),
    "required_args": ("src", "dst"),
    "category": "path_depth",
    "public": True,
    "description": "Check whether a combinational path exists.",
}
```

5. `dispatch_path_op()` 處理 structured request validation 與 function call。
6. `format_path_result()` 處理輸出文字。
7. `test_path_analysis.py` 驗證 pure function 與 prompt parser。
8. `main.py` 只新增 routing hook。

這個 pattern 的重點是讓 regex、dispatcher、formatter、演算法分層，不集中在 `main.py`。

---

## Transformation Extension Pattern

Transformation 跟 analysis 最大差別是它會改 `State.netlist`。

Transformation module 可以依操作類型分開：

```text
tools/transform_fanout.py
tools/transform_cleanup.py
tools/transform_remap.py
tools/transform_rename.py
```

每個 transformation 回傳 operation report：

```python
{
    "op": "insert_buffers_max_fanout",
    "changed": True,
    "added_gates": 12,
    "removed_gates": 0,
    "renamed_signals": [],
}
```

Transformation 更新 netlist 時，同步維護：

- `netlist.gates`
- `netlist.driver`
- `netlist.fanout`
- gate input/output references
- DFF `ports`

之後 1.8 的 transformation statistics 可以從 report history 讀取，不要重新猜。

---

## Testing Policy

每新增一組 tool，至少要有：

- 一個小型 smoke test，用 `simple.v` 或自建小 netlist。
- 至少一個真實 testcase probe。
- `py_compile` 檢查。
- 確認原本已存在的 smoke tests 仍通過。

目前可跑：

```bash
python3 -m py_compile main.py netlist_twoside.py tools/analysis_fanin_fanout.py tools/analysis_logic.py
python3 test_fanin_fanout.py
python3 test_logic_analysis.py
```

如果 tool 會改 netlist，還要加 round-trip check：

```text
parse -> transform -> dump -> parse again
```

---

## Design Rule Of Thumb

如果一個功能可以被問成自然語言，自然語言處理和 EDA 邏輯維持分層。

好的分層：

```text
prompt parser / LLM
  -> structured request
  -> tool dispatcher
  -> pure EDA function
  -> algorithm helper
```

這個分層讓 LLM integration 和 EDA backend 可以獨立演進，也讓每個 tool 都能被獨立測試。
