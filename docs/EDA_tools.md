# EDA Tools — LLM Command Reference

The LLM reads this table to translate a user's natural-language request into operations. Respond with JSON:

```json
{"operations": [{"op": "<op_name>", "args": {<args>}}]}
```

Split a multi-step request into ordered operations. Use signal / gate / file names exactly as written in the request. Each tool below lists what it does and an example command.


## Basic Operation

- `begin_testcase(case_name)` — Start a new testcase; set its name (used for the log file). Command: `{"op": "begin_testcase", "args": {"case_name": "test01"}}`
- `load_design(path)` — Load a gate-level netlist from a .v file as the current design. Command: `{"op": "load_design", "args": {"path": "testcase/test01/test01.v"}}`
- `write_design(path)` — Write the current design to a Verilog file under output/out_v/. Command: `{"op": "write_design", "args": {"path": "test01_out.v"}}`

## 1.1 Gate / Netlist statistics

- `count_fanin_cone_gates(output)` — Number of gates in a primary output's fanin cone. Command: `{"op": "count_fanin_cone_gates", "args": {"output": "n15"}}`
- `max_fanin_cone_depth(output)` — Maximum logic depth of an output's fanin cone. Command: `{"op": "max_fanin_cone_depth", "args": {"output": "n15"}}`
- `count_total_gates()` — Total gate count, broken down by gate type. Command: `{"op": "count_total_gates", "args": {}}`
- `count_gates_by_type_in_cone(output)` — Per-type gate count inside an output's fanin cone. Command: `{"op": "count_gates_by_type_in_cone", "args": {"output": "n15"}}`
- `count_gates_of_type(type)` — Total count of gates of a given type. Command: `{"op": "count_gates_of_type", "args": {"type": "nand"}}`
- `count_primary_inputs_outputs()` — Number of primary inputs and outputs. Command: `{"op": "count_primary_inputs_outputs", "args": {}}`
- `list_primary_inputs_with_widths()` — List primary inputs with their bit widths. Command: `{"op": "list_primary_inputs_with_widths", "args": {}}`
- `list_primary_outputs_with_widths()` — List primary outputs with their bit widths. Command: `{"op": "list_primary_outputs_with_widths", "args": {}}`
- `get_gate_info(gate)` — Type and pin connections of a gate. Command: `{"op": "get_gate_info", "args": {"gate": "g0"}}`
- `list_gates_of_type(type)` — List all gates of a given type. Command: `{"op": "list_gates_of_type", "args": {"type": "xor"}}`
- `list_nand_gates_with_pins()` — List all NAND gates with their I/O signals. Command: `{"op": "list_nand_gates_with_pins", "args": {}}`

## 1.2 Fanin / Fanout / Cone analysis

- `query_input_fanout(input)` — Gates directly driven by a primary input (its fanout). Command: `{"op": "query_input_fanout", "args": {"input": "n5"}}`
- `count_gates_driven_by(gate)` — How many gates a gate drives directly. Command: `{"op": "count_gates_driven_by", "args": {"gate": "g0"}}`
- `list_immediate_successors(gate)` — Immediate successor gates of a gate. Command: `{"op": "list_immediate_successors", "args": {"gate": "g0"}}`
- `transitive_fanin_cone(output)` — All gates in the full fanin cone. Command: `{"op": "transitive_fanin_cone", "args": {"output": "n15"}}`
- `transitive_fanout_cone(input)` — All gates in the full fanout cone. Command: `{"op": "transitive_fanout_cone", "args": {"input": "n5"}}`
- `gates_reachable_from(node)` — Gates reachable from a node along the fanout direction. Command: `{"op": "gates_reachable_from", "args": {"node": "g0"}}`
- `shared_fanin_cone_gates(out1, out2)` — Gates shared by two outputs' fanin cones. Command: `{"op": "shared_fanin_cone_gates", "args": {"out1": "n15", "out2": "n16"}}`
- `gates_connected_to_output(gate)` — Load gates connected to a gate's output. Command: `{"op": "gates_connected_to_output", "args": {"gate": "g0"}}`
- `gates_driven_by_signal(wire)` — Gates driven directly by a signal. Command: `{"op": "gates_driven_by_signal", "args": {"wire": "n5"}}`
- `deepest_fanin_cone_output()` — Primary output with the deepest fanin cone. Command: `{"op": "deepest_fanin_cone_output", "args": {}}`
- `largest_fanin_cone_output()` — Primary output with the largest fanin cone. Command: `{"op": "largest_fanin_cone_output", "args": {}}`
- `highest_fanout_primary_input()` — Primary input with the highest fanout. Command: `{"op": "highest_fanout_primary_input", "args": {}}`
- `max_fanout_of_signal(wire)` — Current maximum fanout of a signal. Command: `{"op": "max_fanout_of_signal", "args": {"wire": "n5"}}`

## 1.3 Path analysis

- `path_exists(src, dst, avoid=None)` — Whether a combinational path exists (optionally avoiding a node). Command: `{"op": "path_exists", "args": {"src": "n2", "dst": "n25"}}`
- `enumerate_paths(src, dst)` — Enumerate all paths between two points. Command: `{"op": "enumerate_paths", "args": {"src": "n3", "dst": "n9"}}`
- `max_logic_depth(src, dst)` — Maximum logic depth between two points. Command: `{"op": "max_logic_depth", "args": {"src": "n3", "dst": "n9"}}`
- `longest_comb_path_depth(src, dst)` — Longest combinational path depth. Command: `{"op": "longest_comb_path_depth", "args": {"src": "n3", "dst": "n9"}}`
- `critical_path_depth(src, dst)` — Critical path depth. Command: `{"op": "critical_path_depth", "args": {"src": "n3", "dst": "n9"}}`
- `max_comb_depth_pi_to_po()` — Max PI->PO combinational depth across the design. Command: `{"op": "max_comb_depth_pi_to_po", "args": {}}`
- `paths_length_zero_pi_to_po()` — Length-0 paths (direct PI-to-PO wires). Command: `{"op": "paths_length_zero_pi_to_po", "args": {}}`
- `all_paths_pass_through(src, dst, node)` — Whether all paths pass through a node. Command: `{"op": "all_paths_pass_through", "args": {"src": "n3", "dst": "n9", "node": "g7"}}`
- `gate_on_max_depth_path(gate)` — Whether a gate lies on a maximum-depth path. Command: `{"op": "gate_on_max_depth_path", "args": {"gate": "g7"}}`
- `register_to_register_paths()` — List register-to-register paths. Command: `{"op": "register_to_register_paths", "args": {}}`
- `max_reg_to_reg_comb_depth()` — Longest register-to-register combinational depth. Command: `{"op": "max_reg_to_reg_comb_depth", "args": {}}`
- `max_pi_to_dff_d_depth()` — Max depth from a PI to a flip-flop D pin. Command: `{"op": "max_pi_to_dff_d_depth", "args": {}}`
- `outputs_with_depth_gt(n)` — Outputs whose cone depth exceeds n. Command: `{"op": "outputs_with_depth_gt", "args": {"n": 4}}`
- `articulation_points_between(src, dst)` — Articulation points between two points. Command: `{"op": "articulation_points_between", "args": {"src": "n3", "dst": "n9"}}`
- `wire_is_cut_between_pi_po(wire)` — Whether a wire is a cut between any PI and PO. Command: `{"op": "wire_is_cut_between_pi_po", "args": {"wire": "n55104"}}`

## 1.4 Functional / logic / formal analysis

- `signals_equivalent(sig_a, sig_b)` — Whether two signals are functionally equivalent. Command: `{"op": "signals_equivalent", "args": {"sig_a": "n55146", "sig_b": "n55104"}}`
- `output_always_constant(output, val)` — Whether an output is always a constant value. Command: `{"op": "output_always_constant", "args": {"output": "n8", "val": 0}}`
- `output_depends_on_input(out, inp)` — Whether an output depends on an input. Command: `{"op": "output_depends_on_input", "args": {"out": "n8", "inp": "n1"}}`
- `derive_boolean_equation(output)` — Boolean equation of an output in terms of PIs. Command: `{"op": "derive_boolean_equation", "args": {"output": "n25"}}`
- `write_logic_expression(wire)` — Logic expression for a wire. Command: `{"op": "write_logic_expression", "args": {"wire": "n11"}}`
- `boolean_function_of_output(output)` — Boolean function of an output. Command: `{"op": "boolean_function_of_output", "args": {"output": "n25"}}`
- `function_symmetric(node, in_a, in_b)` — Whether a function is symmetric in two inputs. Command: `{"op": "function_symmetric", "args": {"node": "n25", "in_a": "n1", "in_b": "n2"}}`
- `exists_nand_pair_equivalent_to(wire)` — Whether some (a,b) makes NAND(a,b) equivalent to the wire. Command: `{"op": "exists_nand_pair_equivalent_to", "args": {"wire": "n25"}}`

## 1.5 Sequential / DFF analysis

- `list_ff_driven_by_clock(clock)` — Flip-flops driven by a given clock. Command: `{"op": "list_ff_driven_by_clock", "args": {"clock": "n0"}}`
- `analyze_dff_d_input_logic()` — Detect enable/hold structures on flip-flop D inputs. Command: `{"op": "analyze_dff_d_input_logic", "args": {}}`
- `count_ff_with_enable_hold()` — Number of flip-flops with an enable/hold structure. Command: `{"op": "count_ff_with_enable_hold", "args": {}}`

## 1.6 Structural health checks

- `list_gates_with_constant_input(type, val)` — Gates that have a constant input. Command: `{"op": "list_gates_with_constant_input", "args": {"type": "and", "val": 0}}`
- `list_gates_with_tied_high()` — Gates with an input tied to 1'b1. Command: `{"op": "list_gates_with_tied_high", "args": {}}`
- `has_dangling_gates()` — Whether any dangling gate exists. Command: `{"op": "has_dangling_gates", "args": {}}`
- `has_redundant_gates()` — Whether any redundant gate exists. Command: `{"op": "has_redundant_gates", "args": {}}`
- `find_floating_signals()` — Floating inputs / unconnected ports. Command: `{"op": "find_floating_signals", "args": {}}`

## 1.7 Equivalence verification

- `verify_equivalent_to_original()` — Equivalent to the netlist as first loaded. Command: `{"op": "verify_equivalent_to_original", "args": {}}`
- `verify_equivalent_to_pre_transform()` — Equivalent to the snapshot before the last transform. Command: `{"op": "verify_equivalent_to_pre_transform", "args": {}}`
- `prove_equivalent_to_loaded()` — Equivalent to the original file on disk. Command: `{"op": "prove_equivalent_to_loaded", "args": {}}`
- `verify_equivalent_sat()` — Equivalent to the original via SAT (gives a counterexample if not). Command: `{"op": "verify_equivalent_sat", "args": {}}`

## 1.8 Post-transformation counting

- `count_added_buffers()` — Buffers added by the last buffer-insertion transform. Command: `{"op": "count_added_buffers", "args": {}}`
- `count_added_gates_of_type(type)` — Gates of a given type added by the last transform. Command: `{"op": "count_added_gates_of_type", "args": {"type": "nor"}}`
- `count_removed_dangling()` — Dangling gates removed by the last cleanup. Command: `{"op": "count_removed_dangling", "args": {}}`
- `count_removed_redundant()` — Redundant gates removed by the last cleanup. Command: `{"op": "count_removed_redundant", "args": {}}`
- `count_merged_gates()` — Gates merged by the last merge transform. Command: `{"op": "count_merged_gates", "args": {}}`
- `count_eliminated_by_const_prop(type)` — Gates of a type eliminated by constant propagation. Command: `{"op": "count_eliminated_by_const_prop", "args": {"type": "and"}}`
- `count_gates_in_cone_after_restructure(output, type)` — Current per-type gate count in a cone. Command: `{"op": "count_gates_in_cone_after_restructure", "args": {"output": "n8", "type": "nand"}}`
- `cone_depth_after_opt(output)` — Current fanin cone depth of an output. Command: `{"op": "cone_depth_after_opt", "args": {"output": "n8"}}`

## 2.1 Fanout / Buffer (transform)

- `insert_buffers_max_fanout(max=4)` — Insert buffers design-wide so every net's fanout <= max. Command: `{"op": "insert_buffers_max_fanout", "args": {"max": 4}}`
- `fanout_optimization(max=4)` — Whole-netlist fanout optimization (same as above). Command: `{"op": "fanout_optimization", "args": {"max": 4}}`
- `insert_buffer_per_load(signal)` — Add one dedicated buffer per load of a signal. Command: `{"op": "insert_buffer_per_load", "args": {"signal": "n5"}}`
- `insert_buffers_on_signal(signal, max=4)` — Buffer-tree only the given signal (e.g. a clock). Command: `{"op": "insert_buffers_on_signal", "args": {"signal": "n0", "max": 4}}`

## 2.2 Depth / Timing optimization (transform)

- `reduce_critical_path_depth()` — Reduce the critical path depth. Command: `{"op": "reduce_critical_path_depth", "args": {}}`
- `depth_optimization()` — Design-wide logic depth optimization. Command: `{"op": "depth_optimization", "args": {}}`
- `minimize_max_path_depth()` — Minimize the maximum path depth. Command: `{"op": "minimize_max_path_depth", "args": {}}`
- `optimize_cone_depth(output, target)` — Reduce an output's cone depth to <= target. Command: `{"op": "optimize_cone_depth", "args": {"output": "n15", "target": 4}}`
- `optimize_outputs_depth_gt(n, target)` — Optimize every output with depth > n toward target. Command: `{"op": "optimize_outputs_depth_gt", "args": {"n": 4, "target": 4}}`

## 2.3 Cleanup / Simplification (transform)

- `remove_dangling_gates()` — Remove dangling gates that do not reach any PO. Command: `{"op": "remove_dangling_gates", "args": {}}`
- `remove_floating_nodes()` — Remove floating nodes. Command: `{"op": "remove_floating_nodes", "args": {}}`
- `prune_unused_gates()` — Delete unused logic. Command: `{"op": "prune_unused_gates", "args": {}}`
- `remove_redundant_gates()` — Remove redundant gates. Command: `{"op": "remove_redundant_gates", "args": {}}`
- `collapse_back_to_back_inverters()` — Collapse NOT-NOT pairs into a wire. Command: `{"op": "collapse_back_to_back_inverters", "args": {}}`
- `constant_propagation(type)` — Simplify gates with constant inputs (optionally by type). Command: `{"op": "constant_propagation", "args": {"type": "and"}}`
- `merge_functionally_equivalent_gates()` — Merge functionally equivalent gates. Command: `{"op": "merge_functionally_equivalent_gates", "args": {}}`
- `merge_structural_duplicate_gates()` — Merge gates with identical type and inputs. Command: `{"op": "merge_structural_duplicate_gates", "args": {}}`

## 2.4 Naming / Connection edits (transform)

- `rename_gate(old, new)` — Rename a gate instance. Command: `{"op": "rename_gate", "args": {"old": "g0", "new": "renamed_gate"}}`
- `rename_wire(old, new)` — Rename a wire and update all references. Command: `{"op": "rename_wire", "args": {"old": "n74", "new": "renamed_wire"}}`
- `reconnect_gate_pin(gate, pin, signal)` — Reconnect a gate input pin to a new signal (may change function). Command: `{"op": "reconnect_gate_pin", "args": {"gate": "g5", "pin": "in0", "signal": "n12"}}`

## 2.5 Technology / Logic Remapping (transform)

- `replace_or_with_nand_not_in_cone(output)` — In an output's cone, rewrite OR gates as NAND+NOT. Command: `{"op": "replace_or_with_nand_not_in_cone", "args": {"output": "n11[0]"}}`
- `convert_cone_to_nor_not(output)` — Rewrite a whole cone using only NOR+NOT. Command: `{"op": "convert_cone_to_nor_not", "args": {"output": "n8"}}`
- `convert_cone_to_nand_not(output)` — Rewrite a whole cone using only NAND+NOT. Command: `{"op": "convert_cone_to_nand_not", "args": {"output": "n8"}}`
- `decompose_xor_in_cone(output)` — Decompose XOR/XNOR in a cone into AND/OR/NOT. Command: `{"op": "decompose_xor_in_cone", "args": {"output": "n15"}}`
- `reconstruct_netlist_and_not_only()` — Rewrite the whole design using only AND+NOT. Command: `{"op": "reconstruct_netlist_and_not_only", "args": {}}`
- `remap_netlist_nand_not_only()` — Rewrite the whole design using only NAND+NOT. Command: `{"op": "remap_netlist_nand_not_only", "args": {}}`
- `convert_xnor_to_nor()` — Convert every XNOR to a NOR-only network. Command: `{"op": "convert_xnor_to_nor", "args": {}}`
- `convert_xor_to_nand()` — Convert every XOR to a NAND-only network (4 NANDs). Command: `{"op": "convert_xor_to_nand", "args": {}}`
- `replace_nand_const1_with_inverter()` — Replace NAND with a constant-1 input by an inverter. Command: `{"op": "replace_nand_const1_with_inverter", "args": {}}`
