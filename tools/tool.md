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

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`How many gates are in the fanin cone of primary output n15?`。也可直接送 JSON op:`{"op": "count_fanin_cone_gates", "args": {"output": "n15"}}`。

---

#### `max_fanin_cone_depth(output)`
- **Description:** 回傳某 output fanin cone 的最大組合邏輯深度（gate level 數）。PI / 常數 / DFF-Q 深度為 0，gate 深度 = 1 + max(輸入深度)。DFF 為邊界。已實作於 `tools/analysis_netlist_stats.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`What is the maximum logic depth of the fanin cone of output n15?`。也可直接送 JSON op:`{"op": "max_fanin_cone_depth", "args": {"output": "n15"}}`。

---

#### `count_total_gates()`
- **Description:** 由 IR 統計各類型 gate 數（AND, OR, NOT, NAND, NOR, XOR, XNOR, BUF, DFF）與總數。已實作於 `tools/analysis_netlist_stats.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Count all the gates in this design and report the total broken down by gate type.`。也可直接送 JSON op:`{"op": "count_total_gates", "args": {}}`。

---

#### `count_gates_by_type_in_cone(output)`
- **Description:** 統計某 output 的 fanin cone 內各類型 gate 數量。已實作於 `tools/analysis_netlist_stats.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Report the number of gates of each type in the fanin cone of output n15.`。也可直接送 JSON op:`{"op": "count_gates_by_type_in_cone", "args": {"output": "n15"}}`。

---

#### `count_gates_of_type(type)`
- **Description:** 統計指定類型（如 NOT、NAND、XOR）的 gate 總數。已實作於 `tools/analysis_netlist_stats.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`How many NAND gates are there in this design?`。也可直接送 JSON op:`{"op": "count_gates_of_type", "args": {"type": "nand"}}`。

---

#### `count_primary_inputs_outputs()`
- **Description:** 回報 primary input / output 的數量，同時提供 port 數與 bit 數。已實作於 `tools/analysis_netlist_stats.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`How many primary inputs and primary outputs does this design have?`。也可直接送 JSON op:`{"op": "count_primary_inputs_outputs", "args": {}}`。

---

#### `list_primary_inputs_with_widths()`
- **Description:** 依 module port 順序列出所有 primary input 及其 bit width。已實作於 `tools/analysis_netlist_stats.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`List all the primary inputs of this design with their bit widths.`。也可直接送 JSON op:`{"op": "list_primary_inputs_with_widths", "args": {}}`。

---

#### `list_primary_outputs_with_widths()`
- **Description:** 依 module port 順序列出所有 primary output 及其 bit width。已實作於 `tools/analysis_netlist_stats.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`List all the primary outputs of this design with their bit widths.`。也可直接送 JSON op:`{"op": "list_primary_outputs_with_widths", "args": {}}`。

---

#### `get_gate_info(gate)`
- **Description:** 回報某 gate 的類型與 pin 連接（primitive gate 回傳 output/inputs；DFF 回傳具名 ports）。已實作於 `tools/analysis_netlist_stats.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`What is the gate type and pin connections of gate g0?`。也可直接送 JSON op:`{"op": "get_gate_info", "args": {"gate": "g0"}}`。

---

#### `list_gates_of_type(type)`
- **Description:** 列出指定類型所有 gate 的 instance 名稱。已實作於 `tools/analysis_netlist_stats.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`List all XOR gates in this design.`。也可直接送 JSON op:`{"op": "list_gates_of_type", "args": {"type": "xor"}}`。

---

#### `list_nand_gates_with_pins()`
- **Description:** 列出所有 NAND gate 及其 input / output signal。已實作於 `tools/analysis_netlist_stats.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`List all NAND gates in this design with their input and output signals.`。也可直接送 JSON op:`{"op": "list_nand_gates_with_pins", "args": {}}`。

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

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`What is the fanout of primary input n5? List all gates that n5 drives directly.`。也可直接送 JSON op:`{"op": "query_input_fanout", "args": {"input": "n5"}}`。

---

#### `count_gates_driven_by(gate)`
- **Description:** 計算某 gate output 直接驅動的 gate 數量。gate 名稱會先解析成其 output signal，再查詢該 signal 的 immediate loads；語意等同 `len(immediate_fanout_gates(gate))`。對應目前 `tools/analysis_fanin_fanout.py` 實作。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`How many gates does gate g0 drive directly?`。也可直接送 JSON op:`{"op": "count_gates_driven_by", "args": {"gate": "g0"}}`。

---

#### `list_immediate_successors(gate)`
- **Description:** 列出某 gate 的 immediate successor gates，也就是直接消耗該 gate output signal 的 load gates。DFF 的 D / CK / RN / SN pins 會依 fanout index 視為 loads。對應目前 `tools/analysis_fanin_fanout.py` 的 `immediate_fanout_gates()`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`List the immediate successor gates of gate g0.`。也可直接送 JSON op:`{"op": "list_immediate_successors", "args": {"gate": "g0"}}`。

---

#### `transitive_fanin_cone(output)`
- **Description:** 回傳 target gate 或 signal 的 transitive fanin cone 內所有 gate instance 名稱。PI / constant 為 fanin 邊界；DFF 在 fanin traversal 中作為 sequential boundary，不跨過 flop 的 Q 往前追。已實作於 `tools/analysis_fanin_fanout.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`List every gate in the transitive fanin cone of output n15.`。也可直接送 JSON op:`{"op": "transitive_fanin_cone", "args": {"output": "n15"}}`。

---

#### `transitive_fanout_cone(input)`
- **Description:** 回傳 source gate 或 signal 的 transitive fanout cone 內所有可達 gate instance 名稱。若 source 是 gate，會先解析成該 gate 的 output signal；走到 DFF load 後會收集該 DFF 但不再穿越其 Q 繼續 traversal。已實作於 `tools/analysis_fanin_fanout.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`List every gate in the transitive fanout cone of input n5.`。也可直接送 JSON op:`{"op": "transitive_fanout_cone", "args": {"input": "n5"}}`。

---

#### `gates_reachable_from(node)`
- **Description:** 列出從某 node（gate 或 signal）沿 fanout 方向可達的所有 gate；語意對應目前的 `transitive_fanout_cone(source)`，使用 combinational/data fanout traversal 並在 DFF 邊界停止。對應目前 `tools/analysis_fanin_fanout.py` 實作。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`List all gates reachable from node g0 along the fanout direction.`。也可直接送 JSON op:`{"op": "gates_reachable_from", "args": {"node": "g0"}}`。

---

#### `shared_fanin_cone_gates(out1, out2)`
- **Description:** 分別計算兩個 target/output 的 transitive fanin cone，回傳兩個 cone 交集中的共用 gate instance 名稱。已實作於 `tools/analysis_fanin_fanout.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Which gates are shared between the fanin cones of outputs n15 and n16?`。也可直接送 JSON op:`{"op": "shared_fanin_cone_gates", "args": {"out1": "n15", "out2": "n16"}}`。

---

#### `gates_connected_to_output(gate)`
- **Description:** 列出直接連到某 gate output signal 的所有 load gates；語意等同查詢該 gate 的 immediate fanout / successors。對應目前 `tools/analysis_fanin_fanout.py` 的 `immediate_fanout_gates()`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Report every gate connected to the output of g0.`。也可直接送 JSON op:`{"op": "gates_connected_to_output", "args": {"gate": "g0"}}`。

---

#### `gates_driven_by_signal(wire)`
- **Description:** 列出由指定 signal/wire 直接驅動的 gate instance 名稱。查詢結果來自 fanout index 的 loads；若需要排除 DFF clock/reset/set pins，可使用目前實作中的 data fanout variant。對應目前 `tools/analysis_fanin_fanout.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Which gates are driven directly by signal n5?`。也可直接送 JSON op:`{"op": "gates_driven_by_signal", "args": {"wire": "n5"}}`。

---

#### `deepest_fanin_cone_output()`
- **Description:** 找出 fanin cone 組合邏輯深度最大的 primary output，深度定義與 `max_fanin_cone_depth(output)` 相同（PI / constant / DFF-Q 深度為 0，gate 深度為 1 + max(input depth)）。目前可由 `tools/analysis_netlist_stats.py` 的 depth query 對所有 PO 掃描取得，尚未作為 1.2 的獨立公開 OP。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Which output bit has the deepest fanin logic cone?`。也可直接送 JSON op:`{"op": "deepest_fanin_cone_output", "args": {}}`。

---

#### `largest_fanin_cone_output()`
- **Description:** 對所有 primary output 計算 fanin cone gate 數，回傳 cone 最大的 output 及其 cone size；若沒有 PO 則回傳空名稱與 0。已實作於 `tools/analysis_fanin_fanout.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Which primary output has the largest fanin cone, and how many gates does it contain?`。也可直接送 JSON op:`{"op": "largest_fanin_cone_output", "args": {}}`。

---

#### `highest_fanout_primary_input()`
- **Description:** 掃描所有 primary inputs，回傳直接 fanout load 數最高的 PI 與 fanout count。`highest_fanout_primary_input()` 統計所有 pins；目前也有 `highest_data_fanout_primary_input()` 可排除 DFF clock/reset/set pins。已實作於 `tools/analysis_fanin_fanout.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Which primary input has the highest fanout?`。也可直接送 JSON op:`{"op": "highest_fanout_primary_input", "args": {}}`。

---

#### `max_fanout_of_signal(wire)`
- **Description:** 回傳指定 signal/wire 目前的直接 fanout load 數，語意等同查詢 fanout index 中該 wire 的 loads 數量；gate load 名稱可由 `immediate_fanout_gates(wire)` 取得。目前可由 `tools/analysis_fanin_fanout.py` 的 index/helper 組合取得，尚未作為獨立公開 OP。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`What is the current maximum fanout of signal n5?`。也可直接送 JSON op:`{"op": "max_fanout_of_signal", "args": {"wire": "n5"}}`。

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

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Does a combinational path exist from primary input n2 to primary output n25? (optionally: that avoids gate g7)`。也可直接送 JSON op:`{"op": "path_exists", "args": {"src": "n2", "dst": "n25"}}`。

---

#### `enumerate_paths(src, dst)`
- **Description:**

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`List every path originating at primary input n3 and terminating at primary output n9.`。也可直接送 JSON op:`{"op": "enumerate_paths", "args": {"src": "n3", "dst": "n9"}}`。

---

#### `max_logic_depth(src, dst)`
- **Description:**

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`What is the maximum logic depth between n3 and n9?`。也可直接送 JSON op:`{"op": "max_logic_depth", "args": {"src": "n3", "dst": "n9"}}`。

---

#### `longest_comb_path_depth(src, dst)`
- **Description:**

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`What is the longest combinational path depth from n3 to n9?`。也可直接送 JSON op:`{"op": "longest_comb_path_depth", "args": {"src": "n3", "dst": "n9"}}`。

---

#### `critical_path_depth(src, dst)`
- **Description:**

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`What is the critical path depth between n3 and n9?`。也可直接送 JSON op:`{"op": "critical_path_depth", "args": {"src": "n3", "dst": "n9"}}`。

---

#### `max_comb_depth_pi_to_po()`
- **Description:**

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`What is the maximum combinational depth from any primary input to any primary output?`。也可直接送 JSON op:`{"op": "max_comb_depth_pi_to_po", "args": {}}`。

---

#### `paths_length_zero_pi_to_po()`
- **Description:**

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Find all paths of length 0 (direct wire connections from PI to PO).`。也可直接送 JSON op:`{"op": "paths_length_zero_pi_to_po", "args": {}}`。

---

#### `all_paths_pass_through(src, dst, node)`
- **Description:**

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Do all paths from n3 to n9 pass through gate g7?`。也可直接送 JSON op:`{"op": "all_paths_pass_through", "args": {"src": "n3", "dst": "n9", "node": "g7"}}`。

---

#### `gate_on_max_depth_path(gate)`
- **Description:**

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Is gate g7 on a maximum-depth path?`。也可直接送 JSON op:`{"op": "gate_on_max_depth_path", "args": {"gate": "g7"}}`。

---

#### `register_to_register_paths()`
- **Description:**

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`List all register-to-register paths in this design.`。也可直接送 JSON op:`{"op": "register_to_register_paths", "args": {}}`。

---

#### `max_reg_to_reg_comb_depth()`
- **Description:**

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`What is the longest register-to-register combinational depth?`。也可直接送 JSON op:`{"op": "max_reg_to_reg_comb_depth", "args": {}}`。

---

#### `max_pi_to_dff_d_depth()`
- **Description:**

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`What is the maximum depth from a primary input to a flip-flop D pin?`。也可直接送 JSON op:`{"op": "max_pi_to_dff_d_depth", "args": {}}`。

---

#### `outputs_with_depth_gt(n)`
- **Description:**

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`List all outputs whose cone depth is greater than 4.`。也可直接送 JSON op:`{"op": "outputs_with_depth_gt", "args": {"n": 4}}`。

---

#### `articulation_points_between(src, dst)`
- **Description:**

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Find the articulation points between n3 and n9.`。也可直接送 JSON op:`{"op": "articulation_points_between", "args": {"src": "n3", "dst": "n9"}}`。

---

#### `wire_is_cut_between_pi_po(wire)`
- **Description:**

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Determine whether wire n55104 is a cut between any primary input and any primary output.`。也可直接送 JSON op:`{"op": "wire_is_cut_between_pi_po", "args": {"wire": "n55104"}}`。

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

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Check whether internal signals n55146 and n55104 are functionally equivalent for all input combinations.`。也可直接送 JSON op:`{"op": "signals_equivalent", "args": {"sig_a": "n55146", "sig_b": "n55104"}}`。

---

#### `output_always_constant(output, val)`
- **Description:** 判斷指定 output 的 Boolean function 是否恆等於 `val`（0 / 1 / true / false）。實作會建立 output expression 並用 BDD constant check 驗證。已實作於 `tools/analysis_logic.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Is output n8 always constant 0?`。也可直接送 JSON op:`{"op": "output_always_constant", "args": {"output": "n8", "val": 0}}`。

---

#### `output_depends_on_input(out, inp)`
- **Description:** 判斷 output 的 Boolean function 是否 functional dependent on 指定 input；若切換該 input 可能改變 output，則回傳 true。已實作於 `tools/analysis_logic.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Does output n8 depend on input n1?`。也可直接送 JSON op:`{"op": "output_depends_on_input", "args": {"out": "n8", "inp": "n1"}}`。

---

#### `derive_boolean_equation(output)`
- **Description:** 從 netlist fanin 遞迴推導某 output 的 Boolean equation，輸出格式為 `output = expression`。常數會轉為 0/1，DFF 或未知 driver 會作為 symbolic variable 邊界。已實作於 `tools/analysis_logic.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Express output n25 as a Boolean equation in terms of the primary inputs.`。也可直接送 JSON op:`{"op": "derive_boolean_equation", "args": {"output": "n25"}}`。

---

#### `write_logic_expression(wire)`
- **Description:** 推導並回傳某 wire/signal 對應的 Boolean logic expression，不包含左側 assignment 名稱。其 expression 建構規則與 `derive_boolean_equation()` 相同。已實作於 `tools/analysis_logic.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Write the Boolean logic expression for wire n11.`。也可直接送 JSON op:`{"op": "write_logic_expression", "args": {"wire": "n11"}}`。

---

#### `boolean_function_of_output(output)`
- **Description:** 回傳某 output 的 Boolean function；目前實作為 `derive_boolean_equation(output)` 的別名，因此輸出同樣是 `output = expression`。已實作於 `tools/analysis_logic.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`What Boolean function does output n25 compute?`。也可直接送 JSON op:`{"op": "boolean_function_of_output", "args": {"output": "n25"}}`。

---

#### `function_symmetric(node, in_a, in_b)`
- **Description:** 檢查某 node/signal 的 Boolean function 是否對兩個指定 input 對稱，也就是交換 `in_a` 與 `in_b` 後 function 是否保持不變。已用 BDD symmetry check 實作於 `tools/analysis_logic.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Is the function of n25 symmetric in inputs n1 and n2?`。也可直接送 JSON op:`{"op": "function_symmetric", "args": {"node": "n25", "in_a": "n1", "in_b": "n2"}}`。

---

#### `exists_nand_pair_equivalent_to(wire)`
- **Description:** 在目標 wire 的 fanin cone 內搜尋既有 internal signals `(a, b)`，判斷是否存在 `NAND(a, b)` 與該 wire functionally equivalent；允許 `a == b`，找不到 cone-local candidate 時會退回掃描部分全設計 internal signals。已實作於 `tools/analysis_logic.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Does there exist a pair of internal signals (a, b) such that NAND(a, b) is equivalent to n25?`。也可直接送 JSON op:`{"op": "exists_nand_pair_equivalent_to", "args": {"wire": "n25"}}`。

---

### 1.5 Sequential / DFF 分析

| Function | 說明 | 首次出現 |
|---|---|---|
| `list_ff_driven_by_clock(clock)` | 某 clock 驅動的 flip-flop | test35, test36 |
| `analyze_dff_d_input_logic()` | 分析 D-pin 是否有 enable/hold 結構 | test40 |
| `count_ff_with_enable_hold()` | 有 enable/hold 結構的 FF 數 | test40 |

#### `list_ff_driven_by_clock(clock)`
- **Description:**

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`List all flip-flops driven by clock n0.`。也可直接送 JSON op:`{"op": "list_ff_driven_by_clock", "args": {"clock": "n0"}}`。

---

#### `analyze_dff_d_input_logic()`
- **Description:**

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Analyze the D-input logic of the flip-flops for enable/hold structures.`。也可直接送 JSON op:`{"op": "analyze_dff_d_input_logic", "args": {}}`。

---

#### `count_ff_with_enable_hold()`
- **Description:**

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`How many flip-flops have an enable/hold structure on their D input?`。也可直接送 JSON op:`{"op": "count_ff_with_enable_hold", "args": {}}`。

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

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`List all AND gates that have a constant 0 input.`。也可直接送 JSON op:`{"op": "list_gates_with_constant_input", "args": {"type": "and", "val": 0}}`。

---

#### `list_gates_with_tied_high()`
- **Description:**

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`List all gates with an input tied to 1'b1.`。也可直接送 JSON op:`{"op": "list_gates_with_tied_high", "args": {}}`。

---

#### `has_dangling_gates()`
- **Description:**

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Are there any dangling gates that do not contribute to any primary output?`。也可直接送 JSON op:`{"op": "has_dangling_gates", "args": {}}`。

---

#### `has_redundant_gates()`
- **Description:**

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Are there any redundant gates in this design?`。也可直接送 JSON op:`{"op": "has_redundant_gates", "args": {}}`。

---

#### `find_floating_signals()`
- **Description:**

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Find any floating signals or unconnected ports in this design.`。也可直接送 JSON op:`{"op": "find_floating_signals", "args": {}}`。

---

### 1.7 等價性驗證

| Function | 說明 | 首次出現 |
|---|---|---|
| `verify_equivalent_to_original()` | 與最初 load 的 netlist 等價 | test32, test34, test36, test40 |
| `verify_equivalent_to_pre_transform()` | 與上一個 transformation 前等價 | test31, test35, test37 |
| `prove_equivalent_to_loaded()` | 與 disk 上原始檔等價 | test33, test38 |
| `verify_equivalent_sat()` | 用 miter + SAT 與最初 load 的 netlist 等價（深 XOR / 大設計用，會給反例） | 補充引擎 |

#### `verify_equivalent_to_original()`
- **Description:** 比對目前設計與「最初 load 的設計快照」（load 時以 deepcopy 存於 state）。序列等價降為暫存器邊界的組合等價：flop 以 Q net 配對，逐一用 BDD 比較每個 PO 與每顆 flop 的 D 函數。已實作於 `tools/verify_equivalence.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Check whether the current netlist is functionally equivalent to the design as originally loaded.`。也可直接送 JSON op:`{"op": "verify_equivalent_to_original", "args": {}}`。

---

#### `verify_equivalent_to_pre_transform()`
- **Description:** 比對目前設計與「上一次 transformation 之前的快照」（`state.pre_transform_netlist`）。若尚未做過任何 transform，退回與 original 比較。BDD 引擎。已實作於 `tools/verify_equivalence.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Prove that the transformed design is equivalent to the pre-transformation netlist.`。也可直接送 JSON op:`{"op": "verify_equivalent_to_pre_transform", "args": {}}`。

---

#### `prove_equivalent_to_loaded()`
- **Description:** 重新 parse disk 上的原始 `.v` 檔（`state.loaded_path`）並與目前設計比對。BDD 引擎。已實作於 `tools/verify_equivalence.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Check whether the current netlist is functionally equivalent to the netlist as last loaded from disk.`。也可直接送 JSON op:`{"op": "prove_equivalent_to_loaded", "args": {}}`。

---

#### `verify_equivalent_sat()`
- **Description:** 與 `verify_equivalent_to_original` 相同的比對對象（最初 load 的設計），但改用 **miter + SAT** 引擎：把兩份 netlist 經 Tseitin 編成共用 PI/flop-Q 變數的 CNF，對每個 PO 與每顆 flop 的 D 函數建 XOR diff 組成 miter，交給 `pysat` 的 Glucose3 求解。UNSAT → 等價;SAT → 不等價並回傳**反例輸入向量**。BDD 會爆炸的深 XOR cone（如 test06 depth 73）用這個。已實作於 `tools/verify_equivalence.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Verify with SAT that the current design is equivalent to the original; give a counterexample if not.`。也可直接送 JSON op:`{"op": "verify_equivalent_sat", "args": {}}`。

---

### 1.8 Transformation 後的計數分析

| Function | 說明 | 首次出現 |
|---|---|---|
| `count_added_buffers()` | 新增多少 BUF | test31 |
| `count_added_gates_of_type(type)` | 新增多少指定類型 gate（如 NOR / NAND remap 後新增量） | test35 |
| `count_removed_dangling()` | 移除多少 dangling gate | test32, test33 |
| `count_removed_redundant()` | 移除多少 redundant gate | test38 |
| `count_merged_gates()` | merge 了多少 gate | test29, test33 |
| `count_eliminated_by_const_prop(type)` | constant propagation 刪了多少 gate | test32, test36, test38, test39 |
| `count_gates_in_cone_after_restructure(output, type)` | restructure 後 cone 內某類 gate 數 | test33, test37 |
| `cone_depth_after_opt(output)` | optimization 後 cone depth | test40 |

#### `count_added_buffers()`
- **Description:** 回報最近一次 buffer insertion transformation 新增的 BUF 數量。已實作於 `tools/analysis_transform_stats.py`，優先讀取 `State.last_transform_report` / `transform_history`，沒有 report 時才嘗試用 pre-transform snapshot 與 current netlist 的 BUF 數量差分估算。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`How many buffers were added by the last buffer-insertion transformation?`。也可直接送 JSON op:`{"op": "count_added_buffers", "args": {}}`。

---

#### `count_added_gates_of_type(type)`
- **Description:** 回報最近一次相關 transformation 新增的指定 gate type 數量，例如 XNOR-to-NOR 或 XOR-to-NAND remap 後新增的 NOR / NAND。已實作於 `tools/analysis_transform_stats.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`How many NOR gates were added by replacing the XNOR gates?`。也可直接送 JSON op:`{"op": "count_added_gates_of_type", "args": {"type": "nor"}}`。

---

#### `count_removed_dangling()`
- **Description:** 回報最近一次 dangling cleanup 移除的 dangling gate 數量。已實作於 `tools/analysis_transform_stats.py`，語意是 transformation delta，不是目前 dangling gate 總數。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`How many dangling gates were removed?`。也可直接送 JSON op:`{"op": "count_removed_dangling", "args": {}}`。

---

#### `count_removed_redundant()`
- **Description:** 回報最近一次 redundancy cleanup 移除的 redundant gate 數量。已實作於 `tools/analysis_transform_stats.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`How many redundant gates were removed?`。也可直接送 JSON op:`{"op": "count_removed_redundant", "args": {}}`。

---

#### `count_merged_gates()`
- **Description:** 回報最近一次 merge transformation 合併 / 移除的 gate 數量。已實作於 `tools/analysis_transform_stats.py`，主要讀取 transformation report 中的 `merged_gates` / `merge_count` / `removed_duplicate_gates` 等欄位。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`How many gates were merged?`。也可直接送 JSON op:`{"op": "count_merged_gates", "args": {}}`。

---

#### `count_eliminated_by_const_prop(type)`
- **Description:** 回報最近一次 constant propagation 消除的指定 gate type 數量。已實作於 `tools/analysis_transform_stats.py`，優先讀取 transformation report 中的 by-type removed / eliminated 統計。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`How many AND gates were eliminated by constant propagation?`。也可直接送 JSON op:`{"op": "count_eliminated_by_const_prop", "args": {"type": "and"}}`。

---

#### `count_gates_in_cone_after_restructure(output, type)`
- **Description:** 回報目前 netlist 中，指定 output fanin cone 內指定 gate type 的數量。已實作於 `tools/analysis_transform_stats.py`，底層重用 `tools/analysis_netlist_stats.py` 的 `count_gates_by_type_in_cone()`，屬於 current-state query，不是 delta。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`How many NAND gates are now in the restructured cone of output n8?`。也可直接送 JSON op:`{"op": "count_gates_in_cone_after_restructure", "args": {"output": "n8", "type": "nand"}}`。

---

#### `cone_depth_after_opt(output)`
- **Description:** 回報目前 netlist 中指定 output fanin cone 的 logic depth。已實作於 `tools/analysis_transform_stats.py`，底層重用 `tools/analysis_netlist_stats.py` 的 `max_fanin_cone_depth()`，屬於 current-state query，不是 delta。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`What is the cone depth of output n8 after optimization?`。也可直接送 JSON op:`{"op": "cone_depth_after_opt", "args": {"output": "n8"}}`。

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

> **共同實作說明（`tools/transform_fanout.py`）**：buffer 用 1-input `buf` gate 表示。每個 transform 流程為 **snapshot → 變動 IR → miter+SAT self-check 等價 → 不等價則 rollback**，並寫入 `state.last_transform_report` / `transform_history`（report key `added_gates_by_type={"buf": N}`，供 1.8 `count_added_buffers` 讀取）。IR 不變式（`driver`/`drivers`/`fanout`）在每次變動後整體 `_reindex` 重建。dispatch 為 state-aware。

#### `insert_buffers_max_fanout(max=4)`
- **Description:** 全 design 掃描,對每個 fanout > max 的 net（PI 與 gate output）插入**平衡 buffer 樹**:loads 每 max 個一組各掛一顆 buffer,層層往上,直到 root net 與每顆 buffer 都只驅動 ≤ max 個 load。功能等價（buf 為 identity）。test21 實測 max fanout 55→4,86 顆 buffer,等價通過。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Insert buffers wherever needed so that no gate drives more than 4 loads. Make sure nothing changes functionally.`。也可直接送 JSON op:`{"op": "insert_buffers_max_fanout", "args": {"max": 4}}`。

---

#### `fanout_optimization(max=4)`
- **Description:** 全 netlist fanout 優化,與 `insert_buffers_max_fanout` 共用同一核心 `_optimize_all_fanout`(分開命名以對應不同 test 措辭)。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Optimize the fanout of the whole netlist so that no net drives more than 4 loads.`。也可直接送 JSON op:`{"op": "fanout_optimization", "args": {"max": 4}}`。

---

#### `insert_buffer_per_load(signal)`
- **Description:** 對指定 signal 的**每一個** load 各掛一顆專屬 buffer（load 隔離）:signal → buf_i → load_i。不改變 signal 的扇出數,但每顆 buffer 只驅動單一 load。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Insert a dedicated buffer for each load of signal n5.`。也可直接送 JSON op:`{"op": "insert_buffer_per_load", "args": {"signal": "n5"}}`。

---

#### `insert_buffers_on_signal(signal, max=4)`
- **Description:** 只對**指定** signal（如 clock / reset）套用平衡 buffer 樹,把該 signal 的 fanout 降到 ≤ max。loads 含 DFF 的 CK/RN/SN pin。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Insert buffers on clock signal n0 so that its fanout is at most 4.`。也可直接送 JSON op:`{"op": "insert_buffers_on_signal", "args": {"signal": "n0", "max": 4}}`。

---

### 2.2 Depth / Timing 優化

| Function | 說明 | 首次出現 |
|---|---|---|
| `reduce_critical_path_depth()` | 降低 critical path depth | test22 |
| `depth_optimization()` | 全 design depth 優化 | test25 |
| `minimize_max_path_depth()` | 最小化最大 path depth | test24, test27, test28 |
| `optimize_cone_depth(output, target)` | 某 output cone depth ≤ target | test26, test27, test33, test40 |
| `optimize_outputs_depth_gt(n, target)` | 所有 depth > n 的 output 都優化 | test27 |

> **共同實作說明（`tools/transform_depth.py` + `algorithm/aig.py`）**
> 引擎 = **AIG 重構**：把要重建的 cone 經 Tseitin 轉成 And-Inverter Graph（NAND/NOR/NOT/AND/OR 統一成 AND+反相邊；XOR/XNOR 保持 atomic 不拆，避免面積爆炸）→ **共享感知平衡**（supergate 只在扇出=1 內部展開，不複製 → 面積中性）→ **反相器吸收式映射**回 `and/nand/or/nor/not`（同極性反相被 NAND/NOR 吸收，只有混合極性才加 NOT）。
> 每次 transform：snapshot → 重建 → **接受準則**：唯有「功能等價(SAT miter) 且深度確實下降」才採用,否則 **rollback 保留原設計**（優化器永不變糟）。寫入 `transform_history`。
> 實測：test27 `optimize_cone_depth` 10→7（−30%）、test25 `depth_optimization` 49→44。NAND 主導且已近最佳的 cone 會被接受準則跳過（保留原樣）。深度量測取 PI→PO / PI→DFF.D / reg→reg 三者最大。
> ⚠️ 限制：大設計（如 test33 64k）的 SAT 自檢偏慢;whole-design 重建較保守,cone-targeted 效果最好。要逼近 ABC 等級深度需更強的 depth-priority tech-mapper。

#### `reduce_critical_path_depth()`
- **Description:** 用 AIG 重構降低 critical-path 深度（whole-design）。改善才採用。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Reduce the critical path depth. Make sure nothing changes functionally.`。也可直接送 JSON op:`{"op": "reduce_critical_path_depth", "args": {}}`。

---

#### `depth_optimization()`
- **Description:** 全設計 AIG 重構降深度（重建所有 PO 與 DFF-D cone）。改善才採用,否則保留原設計。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Perform depth optimization on the combinational logic. Ensure functional equivalence is preserved.`。也可直接送 JSON op:`{"op": "depth_optimization", "args": {}}`。

---

#### `minimize_max_path_depth()`
- **Description:** 最小化最大組合 path 深度,whole-design AIG 重構。語意同 `depth_optimization`,對應不同 test 措辭。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Optimize the logic to minimize maximum path depth. Make sure nothing changes functionally.`。也可直接送 JSON op:`{"op": "minimize_max_path_depth", "args": {}}`。

---

#### `optimize_cone_depth(output, target)`
- **Description:** 只重建指定 output 的 fanin cone,以 AIG 平衡降深度,目標 ≤ target。report 含 `target_met`。cone-targeted 效果最佳（test27 10→7）。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Try to optimize n15 to at most 4 levels deep. Make sure nothing changes functionally.`。也可直接送 JSON op:`{"op": "optimize_cone_depth", "args": {"output": "n15", "target": 4}}`。

---

#### `optimize_outputs_depth_gt(n, target)`
- **Description:** 對所有 cone depth > n 的 primary output 一起做 AIG 重構,目標 ≤ target。report 含 `optimized_outputs` 與 `all_met`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`For each output with depth greater than 4, optimize its cone to meet the depth constraint.`。也可直接送 JSON op:`{"op": "optimize_outputs_depth_gt", "args": {"n": 4, "target": 4}}`。

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

> **共同實作說明（`tools/transform_cleanup.py`）**：全部 equivalence-preserving;dispatch 為 state-aware,每次 snapshot → 變動 → **SAT miter 自檢**,不等價就 rollback,寫入 `transform_history`。共用 `_replace_consumers`（重接 load）、`_dead_gate_elim`（從 PO/DFF pin 反向可達清除死 gate）、`_reindex`。偵測重用 `analysis_structural_health` 的 `dangling_gates`/`redundant_gates`/`find_floating_signals`。

#### `remove_dangling_gates()`
- **Description:** 移除無法反向到達任何 PO / DFF pin 的 gate（dead-code elimination,保留所有 DFF）。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Check if there are any dangling gates that do not contribute to any primary output and remove them.`。也可直接送 JSON op:`{"op": "remove_dangling_gates", "args": {}}`。

---

#### `remove_floating_nodes()`
- **Description:** 移除輸入 floating（無 driver 且非 PI）或輸出無人使用的 gate;回報 floating signals。底層同 DCE。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Remove any floating nodes from the netlist. Ensure functional equivalence is preserved.`。也可直接送 JSON op:`{"op": "remove_floating_nodes", "args": {}}`。

---

#### `prune_unused_gates()`
- **Description:** 刪除其值從不被任何 output 觀察到的邏輯（DCE 變體）。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Delete all gates that do not contribute to any primary output. (a.k.a. eliminate unused logic gates)`。也可直接送 JSON op:`{"op": "prune_unused_gates", "args": {}}`。

---

#### `remove_redundant_gates()`
- **Description:** 移除結構冗餘 gate（與另一顆 gate 同型同輸入),重接到保留者後 DCE 清除。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Remove redundant gates from this design. Ensure the design functionality does not change.`。也可直接送 JSON op:`{"op": "remove_redundant_gates", "args": {}}`。

---

#### `collapse_back_to_back_inverters()`
- **Description:** 把 `NOT(NOT(x))` 折成直接連到 x,buf 亦折除;之後 DCE 清掉變死的 inverter。PO 直驅的雙反相保守保留以確保 PO 有 driver。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Find all back-to-back inverter pairs and collapse them into a wire.`。也可直接送 JSON op:`{"op": "collapse_back_to_back_inverters", "args": {}}`。

---

#### `constant_propagation(type)`
- **Description:** 對含常數輸入的 gate 化簡到 fixpoint:`and(x,1)→x`、`and(x,0)→0`、`or`/`nand`/`nor`/`xor`/`xnor`/`not`/`buf` 同理;`type` 可限定 gate 類型。PO 直驅的化簡轉成 frozen buffer 避免無窮迴圈。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Perform constant propagation to simplify gates with constant inputs (optionally restricted to AND gates).`。也可直接送 JSON op:`{"op": "constant_propagation", "args": {"type": "and"}}`。

---

#### `merge_functionally_equivalent_gates()`
- **Description:** 先做結構重複合併,再對 support ≤ 12 的訊號用 **BDD** 兩兩比對合併功能等價的 gate（如 `or(a,b) ≡ nand(¬a,¬b)`),重接後 DCE。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Merge any pairs of gates that compute the same Boolean function on the same inputs.`。也可直接送 JSON op:`{"op": "merge_functionally_equivalent_gates", "args": {}}`。

---

#### `merge_structural_duplicate_gates()`
- **Description:** 合併同型同輸入（commutative 類排序輸入）的 gate 到 fixpoint,重接 load 後刪除重複者。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Merge any pairs of gates that are structural duplicates (same type and inputs).`。也可直接送 JSON op:`{"op": "merge_structural_duplicate_gates", "args": {}}`。

---

### 2.4 命名 / 連線修改

| Function | 說明 | 首次出現 |
|---|---|---|
| `rename_gate(old, new)` | 重新命名 gate | test24 |
| `rename_wire(old, new)` | 重新命名 wire 並更新 reference | test25 |
| `reconnect_gate_pin(gate, pin, signal)` | 改接 gate input pin | test36 |

> **共同實作說明（`tools/transform_rewire.py`）**：state-aware dispatch。`rename_*` 為純改名,結構與功能不變,直接套用（`verify_method=structural_rename`）;`reconnect_gate_pin` 為刻意改接,可能改變功能,**套用後用 SAT 回報等價狀態但不 rollback**（改接即用戶本意）。

#### `rename_gate(old, new)`
- **Description:** 重新命名 gate instance(更新 `gates` key 與 `gate.name`,reindex)。new 不可與既有 gate 撞名。功能不變。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Change the identifier of gate g0 to renamed_gate and update all references.`。也可直接送 JSON op:`{"op": "rename_gate", "args": {"old": "g0", "new": "renamed_gate"}}`。

---

#### `rename_wire(old, new)`
- **Description:** 重新命名 wire 並更新所有 reference（gate.out / gate.ins / dff ports;若是 PI/PO 也更新 `inputs`/`outputs`/`bus_width`/`port_order` 並標 `was_port`）。new 不可與既有 net 撞名。回報 `references_updated`。test25 改 n7431→renamed_wire。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Change the identifier of wire n74 to renamed_wire and update all references.`。也可直接送 JSON op:`{"op": "rename_wire", "args": {"old": "n74", "new": "renamed_wire"}}`。

---

#### `reconnect_gate_pin(gate, pin, signal)`
- **Description:** 把某 gate 的輸入 pin（comb 用 `in0`/`in1`,DFF 用 `D/CK/RN/SN`）改接到新 signal。回報 `old_signal`/`new_signal` 與 `equivalent`（可能 False = 功能已改,屬預期）。test36。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Reconnect input pin in0 of gate g5 to signal n12.`。也可直接送 JSON op:`{"op": "reconnect_gate_pin", "args": {"gate": "g5", "pin": "in0", "signal": "n12"}}`。

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

> **共同實作說明（`tools/transform_remap.py`）**：所有 op 皆為 **per-gate 的等價邏輯改寫**——把目標 gate 換成以受限 gate basis 表示的等價子網路,並**保留原 gate 的 output net**,所以下游連線完全不動。dispatch 為 state-aware,每次 **snapshot → 改寫 → SAT miter 自檢 → 不等價則 rollback**,並寫入 `state.last_transform_report` / `transform_history`(report 含 `added_gates_by_type`,供 1.8 `count_added_gates_of_type` 讀取)。改寫 fn 透過共用的 `_Builder`(只 emit `and/or/nand/nor/not`)組合各 basis 的 De Morgan 展開;DFF 一律不動。改寫範圍分三類:cone-scoped(`transitive_fanin_cone(output)` 內的 comb gate)、single-gate-type(全 design 指定型別)、whole-design(全部 comb gate)。每次改寫後整體 `_reindex` 重建 driver/fanout 不變式。

#### `replace_or_with_nand_not_in_cone(output)`
- **Description:** 在 `output` 的 transitive fanin cone 內,只把 OR gate 改寫成 `OR(a,b)=NAND(¬a,¬b)`(兩個 NOT + 一個 NAND),其餘 gate 型別保持不動。功能等價。已實作於 `tools/transform_remap.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Replace all 2-input OR gates in the cone of n11[0] with logic built only from NAND and NOT gates.`。也可直接送 JSON op:`{"op": "replace_or_with_nand_not_in_cone", "args": {"output": "n11[0]"}}`。

---

#### `convert_cone_to_nor_not(output)`
- **Description:** 把 `output` fanin cone 內**所有** comb gate 重寫成只用 NOR + NOT 的等價網路(AND/NAND/OR/XOR/XNOR 皆以 De Morgan 展開,XOR 走 `(a&¬b)|(¬a&b)` 的 NOR/NOT 形式)。功能等價。已實作於 `tools/transform_remap.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Restructure the logic cone of output n8 using only NOR and NOT gates.`。也可直接送 JSON op:`{"op": "convert_cone_to_nor_not", "args": {"output": "n8"}}`。

---

#### `convert_cone_to_nand_not(output)`
- **Description:** 把 `output` fanin cone 內**所有** comb gate 重寫成只用 NAND + NOT 的等價網路(XOR 用經典 4-NAND,XNOR 為其再加一級 NOT)。功能等價。已實作於 `tools/transform_remap.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Restructure the logic cone of output n8 using only NAND and NOT gates.`。也可直接送 JSON op:`{"op": "convert_cone_to_nand_not", "args": {"output": "n8"}}`。

---

#### `decompose_xor_in_cone(output)`
- **Description:** 把 `output` fanin cone 內的 XOR / XNOR 拆解成 AND/OR/NOT:`XOR(a,b)=OR(AND(a,¬b),AND(¬a,b))`,XNOR 再加一級 NOT;其餘 gate 不動。功能等價。已實作於 `tools/transform_remap.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Decompose all XOR gates in the fanin cone of n15 into AND, OR, and NOT gates.`。也可直接送 JSON op:`{"op": "decompose_xor_in_cone", "args": {"output": "n15"}}`。

---

#### `reconstruct_netlist_and_not_only()`
- **Description:** 把整個 design 的所有 comb gate 重寫成只用 AND + NOT 的等價網路(OR/NAND/NOR/XOR/XNOR/BUF 全部展開,DFF 保留)。功能等價,以 SAT miter 自檢。已實作於 `tools/transform_remap.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Reconstruct the entire netlist using only AND and NOT gates.`。也可直接送 JSON op:`{"op": "reconstruct_netlist_and_not_only", "args": {}}`。

---

#### `remap_netlist_nand_not_only()`
- **Description:** 把整個 design 的所有 comb gate 重寫成只用 NAND + NOT 的等價網路(NAND 為自然基底,其餘型別 De Morgan 展開,DFF 保留)。功能等價。已實作於 `tools/transform_remap.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Remap the entire design to use only NAND and NOT gates.`。也可直接送 JSON op:`{"op": "remap_netlist_nand_not_only", "args": {}}`。

---

#### `convert_xnor_to_nor()`
- **Description:** 把全 design 每顆 XNOR 改寫成 **NOR-only** 的 4-NOR 網路(4-NAND XOR 的對偶):`t1=NOR(a,b); t2=NOR(a,t1); t3=NOR(b,t1); out=NOR(t2,t3)` 恰為 XNOR。功能等價。已實作於 `tools/transform_remap.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Convert every XNOR gate in this design to an equivalent NOR-only circuit.`。也可直接送 JSON op:`{"op": "convert_xnor_to_nor", "args": {}}`。

---

#### `convert_xor_to_nand()`
- **Description:** 把全 design 每顆 XOR 改寫成 **NAND-only** 的經典 4-NAND 網路:`t1=NAND(a,b); t2=NAND(a,t1); t3=NAND(b,t1); out=NAND(t2,t3)`。功能等價。已實作於 `tools/transform_remap.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Replace all XOR gates in this design with equivalent NAND-only implementations (4 NAND each).`。也可直接送 JSON op:`{"op": "convert_xor_to_nand", "args": {}}`。

---

#### `replace_nand_const1_with_inverter()`
- **Description:** 掃描全 design,把任何一個 input 接 `1'b1` 的 NAND 改成對另一 input 的反相器:`NAND(a,1'b1)=¬a`。只處理含常數 1 的 NAND,功能等價。已實作於 `tools/transform_remap.py`。

- **Usage:** 自然語言指令(每行一個,送進 stdin)範例:`Replace every NAND gate that has a constant 1 input with an inverter.`。也可直接送 JSON op:`{"op": "replace_nand_const1_with_inverter", "args": {}}`。

---
