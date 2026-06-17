# LLM API 使用說明 Linux 版

這份文件只說明如何在 Linux 上使用 API 版本測試本專案的 LLM layer。

## 執行流程

```text
testcase prompt
  -> main.py 呼叫 LLM API
  -> LLM 回傳 JSON operation plan
  -> validator 檢查 op 和 args
  -> dispatcher 呼叫 backend function
  -> main.py 輸出 #RESPONSE / #END
```

LLM 只負責產生 JSON operation，不會直接執行 Python code。

範例 JSON：

```json
{
  "operations": [
    {
      "op": "load_design",
      "args": {
        "path": "testcase/test01/test01.v"
      }
    },
    {
      "op": "write_design",
      "args": {
        "path": "test01_out.v"
      }
    }
  ]
}
```

## 重要檔案

| 檔案 | 功能 |
| --- | --- |
| `main.py` | stdin/stdout 主流程、config 讀取、LLM API 呼叫 |
| `tools/llm_planner.py` | LLM catalog、JSON validator、dispatcher |
| `testcase/test01/prompt.txt` | 最小 API 測試 prompt |

## 基本準備

進入專案目錄：

```bash
cd /path/to/EDA-Final-Project
```

確認 Python 可用：

```bash
python3 --version
```

## 使用 OpenAI API 測試

不要把 API key 寫進程式或 commit 到 repo。請用環境變數。

```bash
export OPENAI_API_KEY='你的 OpenAI API key'
```

建立 `config_openai.yml`：

```bash
cat > config_openai.yml <<'EOF'
provider: openai
openai:
  model: 你的模型名稱
  api_key_env: OPENAI_API_KEY
generation:
  temperature: 0
  max_output_tokens: 4096
  timeout: 60
  strict: true
EOF
```

把 `你的模型名稱` 換成帳號可用的 OpenAI model。

執行 `test01`：

```bash
python3 main.py -config config_openai.yml < testcase/test01/prompt.txt
```

成功時應該看到三個 response：

```text
#RESPONSE 1
Acknowledged. Initialized testcase "test01". ...
#END 1
#RESPONSE 2
Loaded gate-level Verilog from testcase/test01/test01.v successfully.
...
#END 2
#RESPONSE 3
Wrote the current design to "test01_out.v" successfully.
#END 3
```

確認輸出檔：

```bash
ls -lh test01_out.v test01.log
```

## 使用 Anthropic API 測試

設定 API key：

```bash
export ANTHROPIC_API_KEY='你的 Anthropic API key'
```

建立 `config_anthropic.yml`：

```bash
cat > config_anthropic.yml <<'EOF'
provider: anthropic
anthropic:
  model: 你的 Anthropic 模型名稱
  api_key_env: ANTHROPIC_API_KEY
generation:
  temperature: 0
  max_output_tokens: 4096
  timeout: 60
  strict: true
EOF
```

執行：

```bash
python3 main.py -config config_anthropic.yml < testcase/test01/prompt.txt
```

## strict 模式

建議測 API 時使用：

```yaml
strict: true
```

這樣 LLM API 失敗、JSON 格式錯誤、operation 不存在、缺少 args 時，程式會直接回報錯誤。

如果改成：

```yaml
strict: false
```

LLM 失敗時會 fallback 到目前的 rule-based parser。這對 demo 比較方便，但比較不容易看出是不是 LLM 本身失敗。

## 常見錯誤

### API 沒有被使用

確認執行時有加 `-config`：

```bash
python3 main.py -config config_openai.yml < testcase/test01/prompt.txt
```

如果沒有 `-config`，程式會只用 rule-based parser。

### 找不到 `test01.v`

錯誤：

```text
No such file or directory: 'test01.v'
```

目前 `load_design` 已補 fallback：如果已經知道 testcase 是 `test01`，找不到 `test01.v` 時會自動找：

```text
testcase/test01/test01.v
```

如果仍然發生，請確認第一個 response 成功初始化 testcase：

```text
Acknowledged. Initialized testcase "test01".
```

### 想確認 LLM 失敗原因

把 config 設成：

```yaml
strict: true
```

這樣不會自動 fallback，比較容易 debug。

## 目前已接到 API catalog 的 operation

Design I/O：

- `begin_testcase(case_name)`
- `load_design(path)`
- `write_design(path)`

Fanin / fanout / cone：

- `immediate_fanin_gates(gate_or_signal)`
- `immediate_fanout_gates(gate_or_signal)`
- `transitive_fanin_cone(target)`
- `transitive_fanout_cone(source)`
- `count_fanin_cone_gates(target)`
- `count_fanout_cone_gates(source)`
- `shared_fanin_cone_gates(target1, target2)`
- `highest_fanout_signal()`
- `highest_fanout_primary_input()`
- `largest_fanin_cone_output()`

Logic / formal：

- `signals_equivalent(sig_a, sig_b)`
- `output_always_constant(output, val)`
- `output_depends_on_input(output, input)`
- `derive_boolean_equation(output)`
- `write_logic_expression(wire)`
- `boolean_function_of_output(output)`
- `function_symmetric(node, in_a, in_b)`
- `exists_nand_pair_equivalent_to(wire)`
