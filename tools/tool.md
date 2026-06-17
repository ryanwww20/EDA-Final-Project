# EDA Tool 清單

---

## 1. Analysis

---

### 1.1 Gate / Netlist 統計

| Function | 說明 | 首次出現 |
|---|---|---|
| `count_fanin_cone_gates(output)` | fanin cone 內 gate 數 | test03 |
| `max_fanin_cone_depth(output)` | fanin cone 最大 logic depth | test04 |
| `count_total_gates()` | 總 gate 數（與 by-type 重疊） | test20 |
| `count_gates_by_type_in_cone(output)` | 某 output cone 內各 gate 類型數 | test37, test38 |
| `count_gates_of_type(type)` | 某類 gate 總數 | test32, test33, test34, test39, test40 |
| `count_primary_inputs_outputs()` | PI / PO 數量 | test32, test37 |
| `list_primary_inputs_with_widths()` | 列出 PI 與 bit width | test33, test39 |
| `list_primary_outputs_with_widths()` | 列出 PO 與 bit width | test37, test40 |
| `get_gate_info(gate)` | gate 類型 + pin 連接 | test31, test36, test40 |
| `list_gates_of_type(type)` | 列出某類 gate（如 XOR） | test39, test40 |
| `list_nand_gates_with_pins()` | 列出 NAND 與 I/O signal | test35 |

#### `count_fanin_cone_gates(output)`
- **Description:** 回傳某 primary output 的 transitive fanin cone 內 gate 總數。已實作於 `tools/analysis_fanin_fanout.py`。

---

#### `max_fanin_cone_depth(output)`
- **Description:** 回傳某 output fanin cone 的最大組合邏輯深度（gate level 數）。PI / 常數 / DFF-Q 深度為 0，gate 深度 = 1 + max(輸入深度)。DFF 為邊界。已實作於 `tools/analysis_netlist_stats.py`。

---

#### `count_total_gates()`
- **Description:** 由 IR 統計各類型 gate 數（AND, OR, NOT, NAND, NOR, XOR, XNOR, BUF, DFF）與總數。已實作於 `tools/analysis_netlist_stats.py`。

---

#### `count_gates_by_type_in_cone(output)`
- **Description:** 統計某 output 的 fanin cone 內各類型 gate 數量。已實作於 `tools/analysis_netlist_stats.py`。

---

#### `count_gates_of_type(type)`
- **Description:** 統計指定類型（如 NOT、NAND、XOR）的 gate 總數。已實作於 `tools/analysis_netlist_stats.py`。

---

#### `count_primary_inputs_outputs()`
- **Description:** 回報 primary input / output 的數量，同時提供 port 數與 bit 數。已實作於 `tools/analysis_netlist_stats.py`。

---

#### `list_primary_inputs_with_widths()`
- **Description:** 依 module port 順序列出所有 primary input 及其 bit width。已實作於 `tools/analysis_netlist_stats.py`。

---

#### `list_primary_outputs_with_widths()`
- **Description:** 依 module port 順序列出所有 primary output 及其 bit width。已實作於 `tools/analysis_netlist_stats.py`。

---

#### `get_gate_info(gate)`
- **Description:** 回報某 gate 的類型與 pin 連接（primitive gate 回傳 output/inputs；DFF 回傳具名 ports）。已實作於 `tools/analysis_netlist_stats.py`。

---

#### `list_gates_of_type(type)`
- **Description:** 列出指定類型所有 gate 的 instance 名稱。已實作於 `tools/analysis_netlist_stats.py`。

---

#### `list_nand_gates_with_pins()`
- **Description:** 列出所有 NAND gate 及其 input / output signal。已實作於 `tools/analysis_netlist_stats.py`。

---

### 1.2 Fanin / Fanout / Cone 分析

| Function | 說明 | 首次出現 |
|---|---|---|
| `query_input_fanout(input)` | PI fanout + 直接驅動的 gate 列表 | test05 |
| `count_gates_driven_by(gate)` | 某 gate 直接驅動多少 gate | test12 |
| `list_immediate_successors(gate)` | 列舉 immediate successors | test14 |
| `transitive_fanin_cone(output)` | 完整 fanin cone | test15 |
| `transitive_fanout_cone(input)` | 完整 fanout cone | test15 |
| `gates_reachable_from(node)` | 從某節點可達的所有 gate | test31 |
| `shared_fanin_cone_gates(out1, out2)` | 兩 output cone 共用 gate | test31 |
| `gates_connected_to_output(gate)` | 連到某 gate output 的所有 gate | test31, test35, test37 |
| `gates_driven_by_signal(wire)` | 某 signal 驅動哪些 gate | test36 |
| `deepest_fanin_cone_output()` | 哪個 PO fanin cone 最深 | test34, test35 |
| `largest_fanin_cone_output()` | 哪個 PO fanin cone 最大 | test40 |
| `highest_fanout_primary_input()` | fanout 最高的 PI | test36, test38 |
| `max_fanout_of_signal(wire)` | 某 signal 目前最大 fanout | test34, test36, test38 |

#### `query_input_fanout(input)`
- **Description:** 查詢某 primary input / signal 的直接 fanout，回傳由該 input 直接驅動的 gate instance 列表；fanout 數量可由列表長度取得。對應目前 `tools/analysis_fanin_fanout.py` 的 `immediate_fanout_gates()` / fanout index 實作。

---

#### `count_gates_driven_by(gate)`
- **Description:** 計算某 gate output 直接驅動的 gate 數量。gate 名稱會先解析成其 output signal，再查詢該 signal 的 immediate loads；語意等同 `len(immediate_fanout_gates(gate))`。對應目前 `tools/analysis_fanin_fanout.py` 實作。

---

#### `list_immediate_successors(gate)`
- **Description:** 列出某 gate 的 immediate successor gates，也就是直接消耗該 gate output signal 的 load gates。DFF 的 D / CK / RN / SN pins 會依 fanout index 視為 loads。對應目前 `tools/analysis_fanin_fanout.py` 的 `immediate_fanout_gates()`。

---

#### `transitive_fanin_cone(output)`
- **Description:** 回傳 target gate 或 signal 的 transitive fanin cone 內所有 gate instance 名稱。PI / constant 為 fanin 邊界；DFF 在 fanin traversal 中作為 sequential boundary，不跨過 flop 的 Q 往前追。已實作於 `tools/analysis_fanin_fanout.py`。

---

#### `transitive_fanout_cone(input)`
- **Description:** 回傳 source gate 或 signal 的 transitive fanout cone 內所有可達 gate instance 名稱。若 source 是 gate，會先解析成該 gate 的 output signal；走到 DFF load 後會收集該 DFF 但不再穿越其 Q 繼續 traversal。已實作於 `tools/analysis_fanin_fanout.py`。

---

#### `gates_reachable_from(node)`
- **Description:** 列出從某 node（gate 或 signal）沿 fanout 方向可達的所有 gate；語意對應目前的 `transitive_fanout_cone(source)`，使用 combinational/data fanout traversal 並在 DFF 邊界停止。對應目前 `tools/analysis_fanin_fanout.py` 實作。

---

#### `shared_fanin_cone_gates(out1, out2)`
- **Description:** 分別計算兩個 target/output 的 transitive fanin cone，回傳兩個 cone 交集中的共用 gate instance 名稱。已實作於 `tools/analysis_fanin_fanout.py`。

---

#### `gates_connected_to_output(gate)`
- **Description:** 列出直接連到某 gate output signal 的所有 load gates；語意等同查詢該 gate 的 immediate fanout / successors。對應目前 `tools/analysis_fanin_fanout.py` 的 `immediate_fanout_gates()`。

---

#### `gates_driven_by_signal(wire)`
- **Description:** 列出由指定 signal/wire 直接驅動的 gate instance 名稱。查詢結果來自 fanout index 的 loads；若需要排除 DFF clock/reset/set pins，可使用目前實作中的 data fanout variant。對應目前 `tools/analysis_fanin_fanout.py`。

---

#### `deepest_fanin_cone_output()`
- **Description:** 找出 fanin cone 組合邏輯深度最大的 primary output，深度定義與 `max_fanin_cone_depth(output)` 相同（PI / constant / DFF-Q 深度為 0，gate 深度為 1 + max(input depth)）。目前可由 `tools/analysis_netlist_stats.py` 的 depth query 對所有 PO 掃描取得，尚未作為 1.2 的獨立公開 OP。

---

#### `largest_fanin_cone_output()`
- **Description:** 對所有 primary output 計算 fanin cone gate 數，回傳 cone 最大的 output 及其 cone size；若沒有 PO 則回傳空名稱與 0。已實作於 `tools/analysis_fanin_fanout.py`。

---

#### `highest_fanout_primary_input()`
- **Description:** 掃描所有 primary inputs，回傳直接 fanout load 數最高的 PI 與 fanout count。`highest_fanout_primary_input()` 統計所有 pins；目前也有 `highest_data_fanout_primary_input()` 可排除 DFF clock/reset/set pins。已實作於 `tools/analysis_fanin_fanout.py`。

---

#### `max_fanout_of_signal(wire)`
- **Description:** 回傳指定 signal/wire 目前的直接 fanout load 數，語意等同查詢 fanout index 中該 wire 的 loads 數量；gate load 名稱可由 `immediate_fanout_gates(wire)` 取得。目前可由 `tools/analysis_fanin_fanout.py` 的 index/helper 組合取得，尚未作為獨立公開 OP。

---

### 1.3 Path 分析

| Function | 說明 | 首次出現 |
|---|---|---|
| `path_exists(src, dst, avoid=None)` | 是否存在避開某節點的 combinational path | test06 |
| `enumerate_paths(src, dst)` | 列舉兩點間所有 path | test08 |
| `max_logic_depth(src, dst)` | 兩點間最大 logic depth | test10 |
| `longest_comb_path_depth(src, dst)` | 最長 combinational path depth | test11 |
| `critical_path_depth(src, dst)` | critical path depth | test13 |
| `max_comb_depth_pi_to_po()` | 全 design PI→PO 最大 depth | test34 |
| `paths_length_zero_pi_to_po()` | PI 直連 PO 的 length-0 path | test33 |
| `all_paths_pass_through(src, dst, node)` | 是否所有 path 都經過某 gate | test32 |
| `gate_on_max_depth_path(gate)` | gate 是否在 max-depth path 上 | test32 |
| `register_to_register_paths()` | 列出 register-to-register path | test32 |
| `max_reg_to_reg_comb_depth()` | 最長 R2R combinational depth | test40 |
| `max_pi_to_dff_d_depth()` | PI 到 DFF D-pin 最大 depth | test31 |
| `outputs_with_depth_gt(n)` | depth > n 的 output 列表 | test31 |
| `articulation_points_between(src, dst)` | 兩點間 articulation points | test38 |
| `wire_is_cut_between_pi_po(wire)` | wire 是否為 PI–PO cut | test33 |

#### `path_exists(src, dst, avoid=None)`
- **Description:**

---

#### `enumerate_paths(src, dst)`
- **Description:**

---

#### `max_logic_depth(src, dst)`
- **Description:**

---

#### `longest_comb_path_depth(src, dst)`
- **Description:**

---

#### `critical_path_depth(src, dst)`
- **Description:**

---

#### `max_comb_depth_pi_to_po()`
- **Description:**

---

#### `paths_length_zero_pi_to_po()`
- **Description:**

---

#### `all_paths_pass_through(src, dst, node)`
- **Description:**

---

#### `gate_on_max_depth_path(gate)`
- **Description:**

---

#### `register_to_register_paths()`
- **Description:**

---

#### `max_reg_to_reg_comb_depth()`
- **Description:**

---

#### `max_pi_to_dff_d_depth()`
- **Description:**

---

#### `outputs_with_depth_gt(n)`
- **Description:**

---

#### `articulation_points_between(src, dst)`
- **Description:**

---

#### `wire_is_cut_between_pi_po(wire)`
- **Description:**

---

### 1.4 功能 / 邏輯 / 形式分析

| Function | 說明 | 首次出現 |
|---|---|---|
| `signals_equivalent(sig_a, sig_b)` | 兩 signal 是否 functionally equivalent | test17 |
| `output_always_constant(output, val)` | output 是否恒為某值 | test31 |
| `output_depends_on_input(out, inp)` | output 是否依賴某 input | test33 |
| `derive_boolean_equation(output)` | 以 PI 表示 output 的 Boolean 式 | test31 |
| `write_logic_expression(wire)` | 寫出某 wire 的 logic expression | test34 |
| `boolean_function_of_output(output)` | output 的 Boolean function | test35, test37 |
| `function_symmetric(node, in_a, in_b)` | 函數是否對兩 input 對稱 | test36 |
| `exists_nand_pair_equivalent_to(wire)` | 是否存在 (a,b) 使 NAND(a,b) ≡ z | test35 |

#### `signals_equivalent(sig_a, sig_b)`
- **Description:** 將兩個 signal 轉成 Boolean expression / BDD 後檢查 functional equivalence，回傳兩者在所有輸入組合下是否等價。DFF 與不支援的 gate type 會視為 symbolic boundary。已實作於 `tools/analysis_logic.py`。

---

#### `output_always_constant(output, val)`
- **Description:** 判斷指定 output 的 Boolean function 是否恆等於 `val`（0 / 1 / true / false）。實作會建立 output expression 並用 BDD constant check 驗證。已實作於 `tools/analysis_logic.py`。

---

#### `output_depends_on_input(out, inp)`
- **Description:** 判斷 output 的 Boolean function 是否 functional dependent on 指定 input；若切換該 input 可能改變 output，則回傳 true。已實作於 `tools/analysis_logic.py`。

---

#### `derive_boolean_equation(output)`
- **Description:** 從 netlist fanin 遞迴推導某 output 的 Boolean equation，輸出格式為 `output = expression`。常數會轉為 0/1，DFF 或未知 driver 會作為 symbolic variable 邊界。已實作於 `tools/analysis_logic.py`。

---

#### `write_logic_expression(wire)`
- **Description:** 推導並回傳某 wire/signal 對應的 Boolean logic expression，不包含左側 assignment 名稱。其 expression 建構規則與 `derive_boolean_equation()` 相同。已實作於 `tools/analysis_logic.py`。

---

#### `boolean_function_of_output(output)`
- **Description:** 回傳某 output 的 Boolean function；目前實作為 `derive_boolean_equation(output)` 的別名，因此輸出同樣是 `output = expression`。已實作於 `tools/analysis_logic.py`。

---

#### `function_symmetric(node, in_a, in_b)`
- **Description:** 檢查某 node/signal 的 Boolean function 是否對兩個指定 input 對稱，也就是交換 `in_a` 與 `in_b` 後 function 是否保持不變。已用 BDD symmetry check 實作於 `tools/analysis_logic.py`。

---

#### `exists_nand_pair_equivalent_to(wire)`
- **Description:** 在目標 wire 的 fanin cone 內搜尋既有 internal signals `(a, b)`，判斷是否存在 `NAND(a, b)` 與該 wire functionally equivalent；允許 `a == b`，找不到 cone-local candidate 時會退回掃描部分全設計 internal signals。已實作於 `tools/analysis_logic.py`。

---

### 1.5 Sequential / DFF 分析

| Function | 說明 | 首次出現 |
|---|---|---|
| `list_ff_driven_by_clock(clock)` | 某 clock 驅動的 flip-flop | test35, test36 |
| `analyze_dff_d_input_logic()` | 分析 D-pin 是否有 enable/hold 結構 | test40 |
| `count_ff_with_enable_hold()` | 有 enable/hold 結構的 FF 數 | test40 |

#### `list_ff_driven_by_clock(clock)`
- **Description:**

---

#### `analyze_dff_d_input_logic()`
- **Description:**

---

#### `count_ff_with_enable_hold()`
- **Description:**

---

### 1.6 結構健康檢查

| Function | 說明 | 首次出現 |
|---|---|---|
| `list_gates_with_constant_input(type, val)` | 找 constant input 的 gate | test32 |
| `list_gates_with_tied_high()` | input 接 1'b1 的 gate | test37 |
| `has_dangling_gates()` | 是否存在 dangling gate | test32 |
| `has_redundant_gates()` | 是否存在 redundant gate | test38 |
| `find_floating_signals()` | floating input / unconnected port | test37 |

#### `list_gates_with_constant_input(type, val)`
- **Description:**

---

#### `list_gates_with_tied_high()`
- **Description:**

---

#### `has_dangling_gates()`
- **Description:**

---

#### `has_redundant_gates()`
- **Description:**

---

#### `find_floating_signals()`
- **Description:**

---

### 1.7 等價性驗證

| Function | 說明 | 首次出現 |
|---|---|---|
| `verify_equivalent_to_original()` | 與最初 load 的 netlist 等價 | test32, test34, test36, test40 |
| `verify_equivalent_to_pre_transform()` | 與上一個 transformation 前等價 | test31, test35, test37 |
| `prove_equivalent_to_loaded()` | 與 disk 上原始檔等價 | test33, test38 |

#### `verify_equivalent_to_original()`
- **Description:**

---

#### `verify_equivalent_to_pre_transform()`
- **Description:**

---

#### `prove_equivalent_to_loaded()`
- **Description:**

---

### 1.8 Transformation 後的計數分析

| Function | 說明 | 首次出現 |
|---|---|---|
| `count_added_buffers()` | 新增多少 BUF | test31 |
| `count_removed_dangling()` | 移除多少 dangling gate | test32, test33 |
| `count_merged_gates()` | merge 了多少 gate | test29, test33 |
| `count_eliminated_by_const_prop(type)` | constant propagation 刪了多少 gate | test32, test36, test38, test39 |
| `count_gates_in_cone_after_restructure(output, type)` | restructure 後 cone 內某類 gate 數 | test33, test37 |
| `cone_depth_after_opt(output)` | optimization 後 cone depth | test40 |

#### `count_added_buffers()`
- **Description:**

---

#### `count_removed_dangling()`
- **Description:**

---

#### `count_merged_gates()`
- **Description:**

---

#### `count_eliminated_by_const_prop(type)`
- **Description:**

---

#### `count_gates_in_cone_after_restructure(output, type)`
- **Description:**

---

#### `cone_depth_after_opt(output)`
- **Description:**

---

## 2. Transformation & Optimization

---

### 2.1 Fanout / Buffer 相關

| Function | 說明 | 首次出現 |
|---|---|---|
| `insert_buffers_max_fanout(max=4)` | 全 design fanout 限制 | test21 |
| `fanout_optimization(max=4)` | 全 netlist fanout 優化 | test24, test26, test34 |
| `insert_buffer_per_load(signal)` | 某 signal 每個 load 各加 BUF | test31 |
| `insert_buffers_on_signal(signal, max=4)` | 對 clock/reset 等特定 signal 加 buffer | test34, test36, test38 |

#### `insert_buffers_max_fanout(max=4)`
- **Description:**

---

#### `fanout_optimization(max=4)`
- **Description:**

---

#### `insert_buffer_per_load(signal)`
- **Description:**

---

#### `insert_buffers_on_signal(signal, max=4)`
- **Description:**

---

### 2.2 Depth / Timing 優化

| Function | 說明 | 首次出現 |
|---|---|---|
| `reduce_critical_path_depth()` | 降低 critical path depth | test22 |
| `depth_optimization()` | 全 design depth 優化 | test25 |
| `minimize_max_path_depth()` | 最小化最大 path depth | test24, test27, test28 |
| `optimize_cone_depth(output, target)` | 某 output cone depth ≤ target | test26, test27, test33, test40 |
| `optimize_outputs_depth_gt(n, target)` | 所有 depth > n 的 output 都優化 | test27 |

#### `reduce_critical_path_depth()`
- **Description:**

---

#### `depth_optimization()`
- **Description:**

---

#### `minimize_max_path_depth()`
- **Description:**

---

#### `optimize_cone_depth(output, target)`
- **Description:**

---

#### `optimize_outputs_depth_gt(n, target)`
- **Description:**

---

### 2.3 清理 / 簡化

| Function | 說明 | 首次出現 |
|---|---|---|
| `remove_dangling_gates()` | 移除不影響 PO 的 dangling gate/net | test23 |
| `remove_floating_nodes()` | 移除 floating node | test30 |
| `prune_unused_gates()` | 刪 unused logic | test29, test37 |
| `remove_redundant_gates()` | 移除 redundant gate | test38 |
| `collapse_back_to_back_inverters()` | NOT-NOT 合併成 wire | test26 |
| `constant_propagation(type)` | AND/OR/NAND/NOR constant input 簡化 | test32 |
| `merge_functionally_equivalent_gates()` | 合併 functionally equivalent gate pair | test29 |
| `merge_structural_duplicate_gates()` | 合併 structural duplicate | test33 |

#### `remove_dangling_gates()`
- **Description:**

---

#### `remove_floating_nodes()`
- **Description:**

---

#### `prune_unused_gates()`
- **Description:**

---

#### `remove_redundant_gates()`
- **Description:**

---

#### `collapse_back_to_back_inverters()`
- **Description:**

---

#### `constant_propagation(type)`
- **Description:**

---

#### `merge_functionally_equivalent_gates()`
- **Description:**

---

#### `merge_structural_duplicate_gates()`
- **Description:**

---

### 2.4 命名 / 連線修改

| Function | 說明 | 首次出現 |
|---|---|---|
| `rename_gate(old, new)` | 重新命名 gate | test24 |
| `rename_wire(old, new)` | 重新命名 wire 並更新 reference | test25 |
| `reconnect_gate_pin(gate, pin, signal)` | 改接 gate input pin | test36 |

#### `rename_gate(old, new)`
- **Description:**

---

#### `rename_wire(old, new)`
- **Description:**

---

#### `reconnect_gate_pin(gate, pin, signal)`
- **Description:**

---

### 2.5 Technology / Logic Remapping

| Function | 說明 | 首次出現 |
|---|---|---|
| `replace_or_with_nand_not_in_cone(output)` | cone 內 OR → NAND+NOT | test25 |
| `convert_cone_to_nor_not(output)` | cone 改 NOR+NOT | test26, test37 |
| `convert_cone_to_nand_not(output)` | cone 改 NAND+NOT | test27, test33, test37 |
| `decompose_xor_in_cone(output)` | cone 內 XOR → AND/OR/NOT | test27 |
| `reconstruct_netlist_and_not_only()` | 全 design 只用 AND+NOT | test28 |
| `remap_netlist_nand_not_only()` | 全 design 只用 NAND+NOT | test40 |
| `convert_xnor_to_nor()` | XNOR → NOR-only | test33, test34, test35 |
| `convert_xor_to_nand()` | XOR → NAND-only（通常 4 NAND） | test35, test39 |
| `replace_nand_const1_with_inverter()` | NAND 一 input 接 1 → NOT | test32, test40 |

#### `replace_or_with_nand_not_in_cone(output)`
- **Description:**

---

#### `convert_cone_to_nor_not(output)`
- **Description:**

---

#### `convert_cone_to_nand_not(output)`
- **Description:**

---

#### `decompose_xor_in_cone(output)`
- **Description:**

---

#### `reconstruct_netlist_and_not_only()`
- **Description:**

---

#### `remap_netlist_nand_not_only()`
- **Description:**

---

#### `convert_xnor_to_nor()`
- **Description:**

---

#### `convert_xor_to_nand()`
- **Description:**

---

#### `replace_nand_const1_with_inverter()`
- **Description:**

---
