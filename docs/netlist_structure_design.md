# Netlist → Python Data Structure 設計

> **TL;DR**：用 **net-centric** 結構，核心是三個 dict：`driver`（誰產生這條 net）、`fanout`（誰消費這條 net）、`gates`（gate 本體）。已用 parser 跑過全部 40 個 testcase，最大 124k 行 < 1 秒。

---

## 從實際 testcase 學到的關鍵點（spec 沒寫對的）

| 項目 | spec 寫的 | 實際 netlist | 影響 |
|------|-----------|--------------|------|
| DFF | `dff(clk, rst_n, d, q)` 4-pin positional | `dff g0(.RN(n1), .SN(1'b1), .CK(n0), .D(..), .Q(..))` 5-pin named | parser 一定要 handle named-port |
| Gate 順序 | 沒明說 | output 在第一個 arg：`and g0(out, in0, in1)` | 解析時第一個 = driven net |
| Bus bit | 提到有 bus | `n0[0]`、`n3[23]` 每個 bit 是獨立 net | 不能當成整條 `n0` |
| 規模 | 沒提 | 最大 test39 = 124k 行 / 112k gates / 16k dff | 不要用 networkx，用 dict |
| Constant | `1'b1`/`1'b0` | SN pin 常綁 `1'b1` | 解析時要排除常數，不能當 net |

---

## 核心設計：Net-centric

關鍵 insight：**每條 net 只有一個 driver**（gate output 或 PI），但可以有多個 sink。
所以用 net 當 key，查 driver / fanout 都是 O(1)。

```python
class Netlist:
    inputs   : set[str]              # PI nets (bus 已展開成 bit-level)
    outputs  : set[str]              # PO nets
    bus_width: dict[str,(msb,lsb)]   # 寫回 Verilog 時要還原 bus 宣告
    gates    : dict[str, Gate]       # inst name -> Gate
    driver   : dict[str, str]        # net -> 產生它的 gate name (PI 不在裡面)
    fanout   : dict[str, list[str]]  # net -> 消費它的 gate names
```

```python
class Gate:
    name : str            # "g0"
    type : str            # "and" / "dff" / ...
    out  : str            # driven net (dff 的話是 Q)
    ins  : list[str]      # combinational inputs
    ports: dict           # dff 專用: {RN, SN, CK, D, Q}
```

為什麼這樣設計：
- **Graph traversal**（path、depth、cone）→ 用 `driver` 往 fanin 走、`fanout` 往 fanout 走，純 BFS/DFS
- **查 driver** → `driver[net]`，O(1)
- **查 fanout** → `fanout[net]`，O(1)
- **dff 是 sequential boundary** → traversal 時 Q 當 startpoint、D 當 endpoint，不要穿過去（不然 combinational depth 會算錯）

---

## DFF 的特殊處理

```verilog
dff g0(.RN(n1), .SN(1'b1), .CK(n0), .D(n244), .Q(n10));
```
- `CK` = clock → 「list all flip-flops driven by clock n0」就是找 `ports['CK']=='n0'`
- `RN` = async reset（active-low，對應 spec 的 rst_n）
- `SN` = set（active-low，幾乎都綁 `1'b1` = 沒在用）
- `D`/`Q` = data in/out
- traversal：把 dff 當成 fanin cone 的邊界。combinational depth 只算 PI/Q → PO/D 之間的 gate 數

---

## Parser 重點（regex-based，夠快）

```python
# 1. 去 comment
# 2. module header 抓 port order
# 3. input/output 宣告 → 展開 bus bit
# 4. primitive gate: <type> <inst>(net, net[, net]);  output 在 [0]
# 5. dff: 抓 .PIN(net) named ports，排除 1'b0/1'b1 常數
```

實測效能（全部 40 個）：

| testcase | gates | lines | parse time |
|----------|-------|-------|-----------|
| test04 (最小) | 66 | 85 | 0.00s |
| test39 (最大) | 112,300 | 124k | 0.92s |
| **全部 40 個總和** | — | — | **4.06s** |

---

## 建議的擴充查詢（建在這結構上）

這些都是 testcase 真的會問的，全部可以在這個結構上實作：

- `fanin_cone(net)` / `fanout_cone(net)` → DFS，停在 PI/dff
- `max_depth(src, dst)` → DAG 最長路徑（combinational 部分是 DAG）
- `path_exists(src, dst, avoid)` → DFS with blocked node
- `gate_count_by_type()` → 直接 iterate `gates`
- `fanout_of(net)` → `len(fanout[net])`
- equivalence / property check → 把 cone 翻成 z3 expression（另一個主題）

---

## 注意事項

- **不要 mutate input set/output set 來做 transformation**，改 gate 時要同步維護 `driver` 跟 `fanout`，不然後面 query 會錯
- **寫回 Verilog 時**要還原 bus 宣告（用 `bus_width`），不能把 `n0[0]..n0[7]` 散著寫
- **constant `1'b0`/`1'b1`** 在做邏輯運算時要當常數處理，不是 net
- transformation 做完一定要跑 self-check（equivalence / structural assertion）
