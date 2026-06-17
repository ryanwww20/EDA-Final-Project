# EDA tools

# Request Type

## Basic Operation

---

1. Read Design
2. Output Design to a file

## Analysis

---

### **1.1 Gate / Netlist 統計**

- Table
    
    
    | **Tool** | **說明** | **首次出現** |
    | --- | --- | --- |
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

### **1.2 Fanin / Fanout / Cone 分析**

- Table
    
    
    | **Tool** | **說明** | **首次出現** |
    | --- | --- | --- |
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

### **1.3 Path 分析**

- Table
    
    
    | **Tool** | **說明** | **首次出現** |
    | --- | --- | --- |
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

### **1.4 功能 / 邏輯 / 形式分析**

- Table
    
    
    | **Tool** | **說明** | **首次出現** |
    | --- | --- | --- |
    | `signals_equivalent(sig_a, sig_b)` | 兩 signal 是否 functionally equivalent | test17 |
    | `output_always_constant(output, val)` | output 是否恒為某值 | test31 |
    | `output_depends_on_input(out, inp)` | output 是否依賴某 input | test33 |
    | `derive_boolean_equation(output)` | 以 PI 表示 output 的 Boolean 式 | test31 |
    | `write_logic_expression(wire)` | 寫出某 wire 的 logic expression | test34 |
    | `boolean_function_of_output(output)` | output 的 Boolean function | test35, test37 |
    | `function_symmetric(node, in_a, in_b)` | 函數是否對兩 input 對稱 | test36 |
    | `exists_nand_pair_equivalent_to(wire)` | 是否存在 (a,b) 使 NAND(a,b) ≡ z | test35 |

### **1.5 Sequential / DFF 分析**

- Table
    
    
    | **Tool** | **說明** | **首次出現** |
    | --- | --- | --- |
    | `list_ff_driven_by_clock(clock)` | 某 clock 驅動的 flip-flop | test35, test36 |
    | `analyze_dff_d_input_logic()` | 分析 D-pin 是否有 enable/hold 結構 | test40 |
    | `count_ff_with_enable_hold()` | 有 enable/hold 結構的 FF 數 | test40 |

### **1.6 結構健康檢查（分析，不一定修改）**

- Table
    
    
    | **Tool** | **說明** | **首次出現** |
    | --- | --- | --- |
    | `list_gates_with_constant_input(type, val)` | 找 constant input 的 gate | test32 |
    | `list_gates_with_tied_high()` | input 接 1'b1 的 gate | test37 |
    | `has_dangling_gates()` | 是否存在 dangling gate | test32 |
    | `has_redundant_gates()` | 是否存在 redundant gate | test38 |
    | `find_floating_signals()` | floating input / unconnected port | test37 |

### **1.7 等價性驗證（Analysis，常接在 transformation 後）**

- Table
    
    
    | **Tool** | **說明** | **首次出現** |
    | --- | --- | --- |
    | `verify_equivalent_to_original()` | 與最初 load 的 netlist 等價 | test32, test34, test36, test40 |
    | `verify_equivalent_to_pre_transform()` | 與上一個 transformation 前等價 | test31, test35, test37 |
    | `prove_equivalent_to_loaded()` | 與 disk 上原始檔等價 | test33, test38 |

### **1.8 Transformation 後的計數分析（仍是 query）**

- Table
    
    
    | **Tool** | **說明** | **首次出現** |
    | --- | --- | --- |
    | `count_added_buffers()` | 新增多少 BUF | test31 |
    | `count_added_gates_of_type(type)` | 新增多少指定類型 gate（如 NOR / NAND remap 後新增量） | test35 |
    | `count_removed_dangling()` | 移除多少 dangling gate | test32, test33 |
    | `count_removed_redundant()` | 移除多少 redundant gate | test38 |
    | `count_merged_gates()` | merge 了多少 gate | test29, test33 |
    | `count_eliminated_by_const_prop(type)` | constant propagation 刪了多少 gate | test32, test36, test38, test39 |
    | `count_gates_in_cone_after_restructure(output, type)` | restructure 後 cone 內某類 gate 數 | test33, test37 |
    | `cone_depth_after_opt(output)` | optimization 後 cone depth | test40 |
    | `count_ff_with_enable_hold()` | 同上 sequential 分析 | test40 |

## **Transformation & Optimization Tasks**

---

### **2.1 Fanout / Buffer 相關**

- Table
    
    
    | **Tool** | **說明** | **首次出現** |
    | --- | --- | --- |
    | `insert_buffers_max_fanout(max=4)` | 全 design fanout 限制 | test21 |
    | `fanout_optimization(max=4)` | 全 netlist fanout 優化 | test24, test26, test34 |
    | `insert_buffer_per_load(signal)` | 某 signal 每個 load 各加 BUF | test31 |
    | `insert_buffers_on_signal(signal, max=4)` | 對 clock/reset 等特定 signal 加 buffer | test34, test36, test38 |

### **2.2 Depth / Timing 優化**

- Table
    
    
    | **Tool** | **說明** | **首次出現** |
    | --- | --- | --- |
    | `reduce_critical_path_depth()` | 降低 critical path depth | test22 |
    | `depth_optimization()` | 全 design depth 優化 | test25 |
    | `minimize_max_path_depth()` | 最小化最大 path depth | test24, test27, test28 |
    | `optimize_cone_depth(output, target)` | 某 output cone depth ≤ target | test26, test27, test33, test40 |
    | `optimize_outputs_depth_gt(n, target)` | 所有 depth > n 的 output 都優化 | test27 |

### **2.3 清理 / 簡化**

- Table
    
    
    | **Tool** | **說明** | **首次出現** |
    | --- | --- | --- |
    | `remove_dangling_gates()` | 移除不影響 PO 的 dangling gate/net | test23 |
    | `remove_floating_nodes()` | 移除 floating node | test30 |
    | `prune_unused_gates()` | 刪 unused logic | test29, test37 |
    | `remove_redundant_gates()` | 移除 redundant gate | test38 |
    | `collapse_back_to_back_inverters()` | NOT-NOT 合併成 wire | test26 |
    | `constant_propagation(type)` | AND/OR/NAND/NOR constant input 簡化 | test32 |
    | `merge_functionally_equivalent_gates()` | 合併 functionally equivalent gate pair | test29 |
    | `merge_structural_duplicate_gates()` | 合併 structural duplicate | test33 |

### **2.4 命名 / 連線修改**

- Table
    
    
    | **Tool** | **說明** | **首次出現** |
    | --- | --- | --- |
    | `rename_gate(old, new)` | 重新命名 gate | test24 |
    | `rename_wire(old, new)` | 重新命名 wire 並更新 reference | test25 |
    | `reconnect_gate_pin(gate, pin, signal)` | 改接 gate input pin | test36 |

### **2.5 Technology / Logic Remapping**

- Table
    
    
    | **Tool** | **說明** | **首次出現** |
    | --- | --- | --- |
    | `replace_or_with_nand_not_in_cone(output)` | cone 內 OR → NAND+NOT | test25 |
    | `convert_cone_to_nor_not(output)` | cone 改 NOR+NOT | test26, test37 |
    | `convert_cone_to_nand_not(output)` | cone 改 NAND+NOT | test27, test33, test37 |
    | `decompose_xor_in_cone(output)` | cone 內 XOR → AND/OR/NOT | test27 |
    | `reconstruct_netlist_and_not_only()` | 全 design 只用 AND+NOT | test28 |
    | `remap_netlist_nand_not_only()` | 全 design 只用 NAND+NOT | test40 |
    | `convert_xnor_to_nor()` | XNOR → NOR-only | test33, test34, test35 |
    | `convert_xor_to_nand()` | XOR → NAND-only（通常 4 NAND） | test35, test39 |
    | `replace_nand_const1_with_inverter()` | NAND 一 input 接 1 → NOT | test32, test40 |
