#!/usr/bin/env bash
# Run one or more testcases via: python3 main.py <testcase>
#
# Usage:
#   ./scripts/run_tests.sh test01 test10 test15
#   ./scripts/run_tests.sh 1 10 15              # same as test01, test10, test15
#   ./scripts/run_tests.sh 1-5                  # test01 .. test05
#   ./scripts/run_tests.sh test10-test12        # test10, test11, test12
#   ./scripts/run_tests.sh --all
#   ./scripts/run_tests.sh --list
#   ./scripts/run_tests.sh -c config_openai.yml test01

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TESTCASE_DIR="$PROJECT_ROOT/testcase"
MAIN_PY="$PROJECT_ROOT/main.py"
CONFIG=""

STOP_ON_FAIL=1
TESTS=()

usage() {
    sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
    echo
    echo "Options:"
    echo "  -c, --config PATH   Config file passed to main.py (-config)"
    echo "  --all               Run every testcase under testcase/"
    echo "  --list              List available testcases and exit"
    echo "  --continue-on-fail  Keep running after a failed testcase"
    echo "  -h, --help          Show this help"
}

die() {
    echo "Error: $*" >&2
    exit 1
}

normalize_test_name() {
    local token="$1"

    if [[ "$token" =~ ^[0-9]+$ ]]; then
        printf 'test%02d' "$token"
        return
    fi

    if [[ "$token" =~ ^test[0-9]+$ ]]; then
        local num="${token#test}"
        printf 'test%02d' "$num"
        return
    fi

    echo "$token"
}

expand_range() {
    local start_token="$1"
    local end_token="$2"
    local start_num end_num n

    if [[ "$start_token" =~ ^test([0-9]+)$ ]]; then
        start_num="${BASH_REMATCH[1]}"
    elif [[ "$start_token" =~ ^[0-9]+$ ]]; then
        start_num="$start_token"
    else
        die "invalid range start: $start_token"
    fi

    if [[ "$end_token" =~ ^test([0-9]+)$ ]]; then
        end_num="${BASH_REMATCH[1]}"
    elif [[ "$end_token" =~ ^[0-9]+$ ]]; then
        end_num="$end_token"
    else
        die "invalid range end: $end_token"
    fi

    if (( start_num > end_num )); then
        die "invalid range: $start_token > $end_token"
    fi

    for ((n = start_num; n <= end_num; n++)); do
        printf 'test%02d\n' "$n"
    done
}

list_tests() {
    find "$TESTCASE_DIR" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' \
        | sort \
        | while read -r name; do
            if [[ -f "$TESTCASE_DIR/$name/prompt.txt" ]]; then
                echo "$name"
            fi
        done
}

add_test() {
    local name
    name="$(normalize_test_name "$1")"
    TESTS+=("$name")
}

parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -h|--help)
                usage
                exit 0
                ;;
            --list)
                list_tests
                exit 0
                ;;
            --all)
                while IFS= read -r name; do
                    TESTS+=("$name")
                done < <(list_tests)
                shift
                ;;
            -c|--config)
                [[ $# -ge 2 ]] || die "missing value for $1"
                CONFIG="$2"
                shift 2
                ;;
            --continue-on-fail)
                STOP_ON_FAIL=0
                shift
                ;;
            --)
                shift
                while [[ $# -gt 0 ]]; do
                    parse_test_token "$1"
                    shift
                done
                ;;
            -*)
                die "unknown option: $1"
                ;;
            *)
                parse_test_token "$1"
                shift
                ;;
        esac
    done
}

parse_test_token() {
    local token="$1"

    if [[ "$token" =~ ^([0-9]+|test[0-9]+)-([0-9]+|test[0-9]+)$ ]]; then
        while IFS= read -r name; do
            TESTS+=("$name")
        done < <(expand_range "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}")
        return
    fi

    add_test "$token"
}

dedupe_tests() {
    if [[ ${#TESTS[@]} -eq 0 ]]; then
        return
    fi

    local -a unique=()
    local -A seen=()
    local name

    for name in "${TESTS[@]}"; do
        if [[ -z "${seen[$name]+x}" ]]; then
            seen["$name"]=1
            unique+=("$name")
        fi
    done

    TESTS=("${unique[@]}")
}

validate_tests() {
    local name
    for name in "${TESTS[@]}"; do
        [[ -d "$TESTCASE_DIR/$name" ]] || die "unknown testcase: $name"
        [[ -f "$TESTCASE_DIR/$name/prompt.txt" ]] || die "missing prompt.txt for testcase: $name"
    done
}

run_one_test() {
    local name="$1"
    local -a cmd=(python3 "$MAIN_PY")

    if [[ -n "$CONFIG" ]]; then
        cmd+=(-config "$CONFIG")
    fi
    cmd+=("$name")

    echo "============================================================"
    echo "Running: ${cmd[*]}"
    echo "============================================================"

    (
        cd "$PROJECT_ROOT"
        "${cmd[@]}"
    )
}

main() {
    [[ -f "$MAIN_PY" ]] || die "main.py not found: $MAIN_PY"

    parse_args "$@"
    dedupe_tests

    if [[ ${#TESTS[@]} -eq 0 ]]; then
        usage
        die "no testcase specified (use --all, --list, or provide test names)"
    fi

    validate_tests

    local -a passed=()
    local -a failed=()
    local name status=0

    for name in "${TESTS[@]}"; do
        if run_one_test "$name"; then
            passed+=("$name")
            echo
            echo "[PASS] $name"
            echo
        else
            failed+=("$name")
            echo
            echo "[FAIL] $name"
            echo
            status=1
            if [[ "$STOP_ON_FAIL" -eq 1 ]]; then
                break
            fi
        fi
    done

    echo "============================================================"
    echo "Summary"
    echo "============================================================"
    echo "Passed (${#passed[@]}): ${passed[*]:-none}"
    echo "Failed (${#failed[@]}): ${failed[*]:-none}"

    exit "$status"
}

main "$@"
