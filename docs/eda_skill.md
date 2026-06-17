---
name: iccad-problem-a-netlist
description: >
  Domain expertise for ICCAD 2026 Contest Problem A — gate-level netlist analysis and transformation.
  Use whenever a request involves reasoning about, querying, or modifying a flat gate-level Verilog netlist:
  gate counting, fanin/fanout cone queries, logic depth / critical path, path existence and enumeration,
  dominators / articulation points / cuts, functional equivalence and dependence/symmetry checks, Boolean
  equation extraction, clock-domain and register-to-register queries, buffer/fanout splitting, depth
  optimization, dead-logic removal, gate renaming, constant propagation, gate-type remapping (NAND/NOR/AND+NOT),
  XOR/XNOR decomposition, back-to-back inverter collapse, and structural/functional gate merging. This skill
  teaches HOW to solve each task class correctly and defines every technical term that appears; the
  round/loop protocol is defined separately in the prompt.
---

# ICCAD Problem A — Netlist Analysis & Transformation

Your domain knowledge for solving gate-level netlist tasks **correctly**. The interaction loop is defined in
the prompt; this skill defines *what each task means* and *how to solve it*. The callable operations are in
`tool.md` — this skill tells you which to compose, in what order, and how to verify the result.

A transformation that looks right but breaks functionality, or an analysis answer that's wrong, scores **zero**
for the whole testcase. Verify everything.

---

## 1. Netlist Format & Conventions

- Flat design, **one top module**. No hierarchy.
- **Gate instantiation syntax: output first, then inputs.**
  `nand g2(n13, n4961, n5012);` means `g2` is a NAND with output `n13`, inputs `n4961` and `n5012`.
  Instance names are `g0, g1, ...`. Signal/net names are `nNNN` (and may be bus bits like `n13[0]`).
- Primitives: `and or nand nor xor xnor` are **2-input, 1-output**; `not buf` are **1-input, 1-output**.
- **DFF** (`dff`): `posedge clk`, asynchronous active-low reset `rst_n` (resets `q` to `1'b0`), data `d`, output `q`.
- Ports may be **scalar or bus** (`input [7:0] n0;`). A name like `n0` may be a whole bus; a bit is `n0[0]`.
  When a request names a bus without an index, operate per-bit unless context says otherwise.
- **Constants**: `1'b0`, `1'b1` are signal sources (used in constant-propagation tasks).

---

## 2. The Graph Model (foundation for everything)

Model the netlist as a **directed graph**: nodes = gate instances / DFFs / ports / constants; edges = nets,
directed **driver → load**.

- **Primary input (PI)** = module input port. **Primary output (PO)** = module output port.
- **Combinational graph** = the graph with **all DFFs cut**: treat each DFF output `q` as a pseudo-PI and each
  DFF input `d` as a pseudo-PO. The result is a **DAG** (directed acyclic graph). *Always cut DFFs before any
  combinational traversal — otherwise feedback loops break your algorithms.*
- **Driver** of a net = the gate/port whose output is that net. **Load(s)** = gates whose input is that net.
- **Fanout of a signal** = the set (or count) of loads it **drives directly** (its immediate successors).
- **Fanin of a gate** = the signals feeding its inputs.
- **Immediate successors** of gate g = the gates directly driven by g's output.
- **Immediate predecessors** of gate g = the gates driving g's inputs.

Two reusable structures behind most queries:

- **Transitive fanin cone of signal s** = all nodes that can reach `s` through combinational edges (walk
  backward from `s`, stop at PIs / DFF-q / constants). "Logic cone of s" usually means this.
- **Transitive fanout cone of signal s** = all nodes reachable forward from `s` (stop at POs / DFF-d).
- **Reachable from n** = the transitive fanout set of n.

---

## 3. Depth / Critical Path (one concept, many names)

These phrasings **all mean the same thing** — longest combinational path measured in **gate levels**:
- "maximum logic depth", "longest combinational path depth", "critical path depth", "logic depth", "levels deep".

Method:
- Level of a PI / DFF-q / constant = 0. `level(g) = 1 + max(level of its fanins)`. Compute by topological order
  over the combinational DAG. Depth of a cone / of a signal = its level. **Depth = gate count along the path,
  not net count.**
- **"Depth from input X to output Y"** → restrict to nodes on X→Y paths (intersection of X's fanout cone and
  Y's fanin cone), longest path within that subgraph.
- **"Max depth from any PI to any DFF D-pin"** → longest level reached at any DFF `d` input.
- **"Max combinational depth on any register-to-register path"** → longest level among DFF-d pins counting only
  from DFF-q / PI sources (i.e., reg→reg stage delay).
- **"How many outputs have depth > 4"** → count POs whose fanin-cone depth exceeds 4.
- **"Which output has the deepest / largest fanin cone"** → compare per-PO depth (or cone gate-count for
  "largest cone" — read which metric the wording asks for: *deepest* = depth, *largest* = gate count).

Always report a **witness path** (the actual gate sequence) alongside a depth value.

---

## 4. Path Queries

- **Combinational path** = a directed path in the combinational DAG (does not pass through a DFF).
- **"Path from A to B avoiding node C"** → remove C from the graph, test reachability A→B. If B still reachable
  → such a path **exists** (return it as witness). If not → it doesn't.
- **"Does every path from A to B pass through C?"** → C is a **dominator** of B w.r.t. A. Equivalent test:
  remove C; if B is *no longer* reachable from A → YES (every path goes through C); if still reachable → NO,
  and the surviving path is your counterexample. **Never answer this from structure by eye — run the cut test.**
- **"List / enumerate every path from A to B"** → enumerate all simple directed paths (DFS with path stack).
  Beware exponential blow-up; if the count is huge, report the count and a representative sample as the tool allows.
- **"Paths of length 0 (direct PI→PO)"** → a PI net that is *directly* a PO (wire-through), zero gates between.
- **Articulation point / cut vertex (between A and B)** = a node whose removal disconnects A from B — i.e., a
  dominator that lies on **all** A→B paths. Find by: for each candidate on some A→B path, remove it and retest
  reachability. (Equivalent to dominator-tree analysis.)
- **"Is wire W a cut between any PI and any PO?"** → does there exist a PI/PO pair such that removing W
  disconnects them (W lies on every path between that pair)? Same dominator test, existentially over pairs.

---

## 5. Functional Queries (need Boolean reasoning, not structure)

Build the Boolean function(s) and reason with SAT / BDD / truth tables — **structural inspection is not enough**.

- **Functional equivalence of two signals a, b** → `a XOR b` is unsatisfiable (miter: assert `a != b`, if UNSAT
  they're equivalent). "produce identical logic values for all inputs" / "equivalent for all input combinations"
  = same thing.
- **"Is output Z always 0 regardless of inputs?"** → check `Z = 1` is UNSAT (Z is the constant-0 function).
  Likewise "always 1" → `Z = 0` UNSAT.
- **Functional dependence — "does output Y depend on input X?"** → Y depends on X iff there's an assignment where
  flipping X flips Y (Boolean difference `∂Y/∂X ≠ 0`). Structural presence of X in Y's fanin cone is **necessary
  but not sufficient** — X can be in the cone yet functionally redundant. Confirm functionally.
- **Functional symmetry — "is f symmetric w.r.t. inputs a and b?"** → swapping a and b leaves f unchanged:
  `f(...,a,...,b,...) ≡ f(...,b,...,a,...)`. Build both and check equivalence.
- **Boolean equation / "what function does output Y compute in terms of PIs"** → compose the function of Y's
  fanin cone down to PIs; emit a Boolean expression (e.g. SOP) over PI names.
- **"Do there exist signals a,b already in the netlist s.t. NAND(a,b) ≡ Z?"** → functional matching: search
  existing nets for a pair whose NAND equals Z (equivalence-check candidates; prune by support/cone first).
- **"Gates shared between fanin cones of Y1 and Y2"** → set intersection of the two transitive fanin cones.

---

## 6. Structural / Inventory Queries (cheap, exact)

- **Gate count by type** → tally instances per primitive (`and/or/not/nand/nor/xor/xnor/buf`) and `dff`.
- **Total gate count** → sum of all gate instances.
- **Gate type & pin connections of g** → report its primitive type and which nets are on output/input pins.
- **"Gates driven by g" / "gates connected to the output of g"** → g's immediate successors (count or list).
- **Number of PIs / POs** → count input / output ports (note bus width when asked "with their bit widths").
- **Highest-fanout PI** → PI with the most direct loads.
- **Gates with an input tied to constant** (`1'b0`/`1'b1`) → scan instances for constant input nets.
- **Floating / unconnected** → a **floating input** has no driver; an **unconnected output port** drives nothing;
  a **floating signal** is a net that's declared/driven but feeds no load and isn't a PO.
- **DFFs driven by clock n0** → all DFFs whose `clk` net is n0 (this is a **clock domain**: DFFs sharing the same
  clock net are in one domain; reset net is irrelevant to domain).
- **Register-to-register path** → a combinational path from a DFF `q` (source) to a DFF `d` (sink).
- **Enable / hold structure on a DFF D-input** → logic feeding `d` that re-selects the current `q` under some
  condition — typically a 2:1 mux (`d = sel ? new : q`) or an AND/OR recirculation. Detect by checking whether
  `q` feeds back into its own `d` cone through such a select.

---

## 7. Transformations — pattern: **locate → edit → verify**

Verification (Section 9) is mandatory after every edit. When editing, **preserve the net names on the boundary
of the edit** so the rest of the graph stays correctly wired.

### 7.1 Fanout / buffer insertion
- **"Insert buffers so no gate drives more than K loads"** (fanout optimization) → for any net with > K loads,
  build a **balanced buffer tree**: split loads into groups of ≤ K, drive each group via a `buf`, recurse until
  the source's direct fanout ≤ K. Buffers are identity → functionality trivially preserved; still verify
  `fanout ≤ K` on every node.
- **"Insert a dedicated BUF per load of signal s"** → one `buf` per load, each load driven through its own buffer.
- **Clock / reset buffering** → same fanout-splitting, applied to the clock or reset net.

### 7.2 Depth optimization / restructuring
- **"Reduce critical path depth / minimize max depth by restructuring"** → re-balance deep logic: turn linear
  gate chains into **balanced trees** (associativity of AND/OR/XOR), share common subexpressions. Preserve the
  Boolean function. Verify equivalence + report new depth.
- **"Optimize cone of Y to depth ≤ D"** → depth-bounded re-synthesis of Y's cone; if already ≤ D, report it's
  already optimal (don't regress). Hard constraint: final depth ≤ D **and** equivalent.

### 7.3 Dead / redundant logic removal (many synonyms)
"dangling", "floating", "unused", "dead", "prune", "trim", "sweep", "remove gates not contributing to any PO".
- A gate is **live** iff it's in the fanin cone of some PO or some DFF `d`. Everything else is **dead** — remove it.
- **Redundant gates** (a stronger notion) = gates removable *without changing functionality* even if structurally
  connected (e.g. an input that's functionally don't-care / ATPG-redundant). Removing pure dead logic is the safe
  subset; for "redundant" go by functional equivalence after removal.
- Report counts when asked ("how many were removed").

### 7.4 Renaming
- **Rename gate / wire / signal and update all references** → change the identifier everywhere it appears
  (driver and all loads). Purely syntactic; functionality unchanged. Verify equivalence as a sanity check.

### 7.5 Constant propagation (exact identities)
"Simplify gates with constant inputs":
- `NAND(a, 1) = NOT(a)` → replace with inverter. `NAND(a, 0) = 1` (constant).
- `AND(a, 0) = 0`. `AND(a, 1) = a` (wire).
- `OR(a, 1) = 1`. `OR(a, 0) = a` (wire).
- `NOR(a, 0) = NOT(a)`. `NOR(a, 1) = 0`.
- `XOR(a, 0) = a`. `XOR(a, 1) = NOT(a)`. `XNOR(a,0)=NOT(a)`. `XNOR(a,1)=a`.
Propagate folded constants forward (a new constant can trigger further simplification). Report how many gates
were eliminated/converted.

### 7.6 Back-to-back inverter collapse
- `NOT(NOT(a)) = a` → remove both inverters, connect the load directly to `a` (a wire). Find all `not→not`
  chains and collapse. Verify equivalence; report count.

### 7.7 Gate-type conversion / technology remapping (exact identities)
When asked to rebuild logic using a restricted gate set, use these and let synthesis handle the rest:
- **OR → NAND+NOT**: `a|b = NAND(NOT a, NOT b)`.
- **AND → NAND+NOT**: `a&b = NOT(NAND(a,b))`.
- **XOR → 4×NAND**: `w=NAND(a,b); out=NAND(NAND(a,w), NAND(b,w))`.
- **XNOR → NOR-only / NOR+NOT**: `a XNOR b = NOT(a XOR b)`; map via De Morgan into NOR/NOT (a known multi-gate
  expansion — the exact NOR count comes from the mapping the tool performs).
- **XOR → AND/OR/NOT decomposition**: `a^b = (a&~b) | (~a&b)`.
- **Remap whole netlist to {AND,NOT}** or **{NAND,NOT}** → AIG-style two-level decomposition: every gate becomes
  AND+inverters (or NAND+inverters). Delegate the global mapping to the synthesis/remap tool, then verify
  equivalence to the original.
- Restricting a **cone** to {NAND,NOT} or {NOR,NOT} → same, scoped to that PO's fanin cone.
Always re-verify equivalence and report the resulting gate counts the question asks for.

### 7.8 Gate merging
- **Structural duplicates / structural hashing** → two gates of the **same type with the same inputs** (account
  for commutativity of 2-input gates) compute the same function; merge them, rewire loads to the survivor.
- **Functionally equivalent gate pairs** → broader: same Boolean function even if structurally different; confirm
  by equivalence check before merging. Report merge count.

### 7.9 Pin reconnection
- **"Reconnect input pin A of g to signal s"** → change that input net; this **does** alter logic, so only do it
  when the task says functionality must be preserved *and* you've verified the new connection is equivalent —
  otherwise report the functional impact.

---

## 8. Optimization Scoring

Some tasks (depth-bounded cone optimization, minimize gate count) are **ranked**: among solutions that satisfy
**all hard constraints**, lower cost (gate count) ranks better against the best valid solution. A smaller netlist
that violates a constraint or changes function scores **zero** — validity first, then minimize.

---

## 9. Verification Discipline (non-negotiable)

After every transformation:
1. **Functional check** — if logic must not change, build a **miter** against the pre-edit (or originally-loaded)
   design and SAT-check for any differing input. For edits that intentionally change logic (e.g. gating), verify
   only the intended nets changed and the rest is equivalent.
2. **Structural check** — confirm the exact bound the task demands: `fanout ≤ K`, `depth ≤ D`, only the allowed
   gate types present in the target region, references fully updated after a rename, etc.

"Prove equivalence to the pre-transformation / originally-loaded netlist", "confirm still equivalent to original",
"verify equivalent to netlist as last loaded from disk" → run the miter against the saved reference snapshot.
If any check fails, **do not report success** — re-plan and fix.

---

## 10. Pre-Action Checklist

1. **Classify** — inventory query / structural query / path query / functional query / transformation / optimization.
2. **Resolve the target** — exact signal, gate, cone, pattern, or PI/PO pair (mind bus bits like `n0[0]`).
3. **Hard constraints** — what must hold at the end (equivalence, depth, fanout, gate-type restriction)?
4. **Cut DFFs** for any combinational traversal.
5. **Compose** the operations: locate → analyze/edit → verify.
6. **Evidence** — analysis answers carry a witness (path / value / counterexample / list); transformations carry
   confirmation that constraints hold and the requested counts.
