#!/usr/bin/env bash
# Driver for the a2a-testbed GitHub Action (action.yml). Reads INPUT_*
# environment variables, runs `lint-card` and/or `conformance`, writes
# reports to $RUNNER_TEMP/a2a-conformance and sets step outputs. It
# never fails the step itself; action.yml's last step enforces the
# combined exit code so the SARIF upload always runs first.
set -uo pipefail

url="${INPUT_URL:-}"
card="${INPUT_CARD:-}"
out="${GITHUB_OUTPUT:-/dev/null}"

if [ -z "$url" ] && [ -z "$card" ]; then
  echo "::error::a2a-testbed action: set 'url' (live sweep), 'card' (AgentCard lint), or both"
  echo "exit-code=2" >> "$out"
  exit 0
fi

if [ -n "${INPUT_PACKAGE:-}" ]; then
  tool=(uvx --quiet --from "$INPUT_PACKAGE" a2a-testbed)
else
  # Build from the action's own checkout, so the tool always matches the
  # action ref. [tool.uv] cache-keys in pyproject.toml make uv rebuild it
  # whenever the sources change.
  tool=(uvx --quiet --from "${ACTION_PATH:?ACTION_PATH not set}" a2a-testbed)
fi

# One directory per invocation, so two uses of the action in a job do not
# overwrite each other's reports.
mkdir -p "${RUNNER_TEMP:-/tmp}"
report_dir="$(mktemp -d "${RUNNER_TEMP:-/tmp}/a2a-conformance.XXXXXX")" || {
  echo "::error::cannot create a report directory under ${RUNNER_TEMP:-/tmp}"
  echo "exit-code=2" >> "$out"
  exit 0
}
echo "report-dir=$report_dir" >> "$out"

common=()
baseline="${INPUT_BASELINE:-.a2a-conformance.yaml}"
if [ "$baseline" = "none" ]; then
  common+=(--baseline none)
elif [ -f "$baseline" ] || [ "$baseline" != ".a2a-conformance.yaml" ]; then
  # A non-default path that does not exist is passed through so the CLI
  # reports it (exit 2) instead of silently running without it.
  common+=(--baseline "$baseline")
fi
[ "${INPUT_STRICT:-false}" = "true" ] && common+=(--strict)
[ -n "${INPUT_PROTOCOL_VERSION:-}" ] && common+=(--protocol-version "$INPUT_PROTOCOL_VERSION")

category="${INPUT_SARIF_CATEGORY:-}"
codes=()

# Exit 1 means "a contract failed" only when the tool got far enough to
# write its report; otherwise it is an install failure or a crash, which
# must not be reported as contract failures.
record() {
  local code="$1" report="$2"
  if [ "$code" = 1 ] && [ ! -s "$report" ]; then
    echo "::error::a2a-testbed exited 1 without writing $report (install failure or crash)"
    code=2
  fi
  codes+=("$code")
}

if [ -n "$card" ]; then
  echo "::group::a2a-testbed lint-card $card"
  cat_args=()
  [ -n "$category" ] && cat_args=(--sarif-category "$category/lint")
  "${tool[@]}" lint-card "$card" ${common[@]+"${common[@]}"} ${cat_args[@]+"${cat_args[@]}"} \
    -o "$report_dir/lint.json" -o "$report_dir/lint.sarif" \
    -o "$report_dir/lint.xml" -o "$report_dir/lint.md"
  record $? "$report_dir/lint.json"
  echo "::endgroup::"
fi

if [ -n "$url" ]; then
  location="${INPUT_SARIF_LOCATION:-}"
  [ -z "$location" ] && location="${card:-agent-card.json}"
  echo "::group::a2a-testbed conformance $url"
  cat_args=()
  [ -n "$category" ] && cat_args=(--sarif-category "$category/sweep")
  "${tool[@]}" conformance "$url" ${common[@]+"${common[@]}"} ${cat_args[@]+"${cat_args[@]}"} \
    --push-receiver "${INPUT_PUSH_RECEIVER:-auto}" \
    --timeout "${INPUT_TIMEOUT:-45}" --retries "${INPUT_RETRIES:-1}" \
    --sarif-location "$location" \
    -o "$report_dir/results.json" -o "$report_dir/results.sarif" \
    -o "$report_dir/results.xml" -o "$report_dir/summary.md"
  record $? "$report_dir/results.json"
  echo "::endgroup::"
fi

# Combine: a failure (1) outranks a usage/unreachable error (2), which
# outranks "agent did not answer some checks" (3), which outranks pass.
final=0
for c in ${codes[@]+"${codes[@]}"}; do
  case "$c" in
    1) final=1 ;;
    2) [ "$final" != 1 ] && final=2 ;;
    3) [ "$final" = 0 ] && final=3 ;;
    0) ;;
    *) [ "$final" = 0 ] && final=2 ;;
  esac
done
echo "exit-code=$final" >> "$out"

if compgen -G "$report_dir/*.sarif" > /dev/null; then
  echo "sarif=$report_dir" >> "$out"
fi
exit 0
