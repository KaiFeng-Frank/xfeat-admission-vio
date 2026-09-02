#!/usr/bin/env bash
# render_config.sh BASE_YAML OUT_YAML OUTPUT_PATH
#
# Renders a run config from the frozen base estimator config by rewriting
# ONLY the `output_path:` line. Every other byte of the base config is
# preserved verbatim; the script aborts if more than that one line changed.
set -euo pipefail

base=${1:?usage: render_config.sh BASE_YAML OUT_YAML OUTPUT_PATH}
out=${2:?usage: render_config.sh BASE_YAML OUT_YAML OUTPUT_PATH}
newpath=${3:?usage: render_config.sh BASE_YAML OUT_YAML OUTPUT_PATH}

[[ -f "$base" ]] || { echo "render_config: missing base config: $base" >&2; exit 2; }
newpath=${newpath%/}
mkdir -p "$(dirname "$out")"

# The path is passed through the environment, NOT `awk -v`: -v expands backslash
# escape sequences in the assigned value, which would silently rewrite a path
# containing a backslash while still passing the one-line diff self-check below.
NEWPATH="$newpath" awk '
  BEGIN { p = ENVIRON["NEWPATH"] }
  /^[[:space:]]*output_path[[:space:]]*:/ && !done { printf "output_path: \"%s\"\n", p; done=1; next }
  { print }
  END { if (!done) printf "output_path: \"%s\"\n", p }
' "$base" > "$out"

n=$(grep -c '^[[:space:]]*output_path[[:space:]]*:' "$out" || true)
[[ "$n" -eq 1 ]] || { echo "render_config: produced $n output_path lines in $out" >&2; exit 2; }

# diff must touch exactly one line (one '<' + one '>')
changed=$(diff "$base" "$out" | grep -c '^[<>]' || true)
if [[ "$changed" -gt 2 ]]; then
  echo "render_config: refused - $changed lines differ from the frozen base, expected <=2" >&2
  diff "$base" "$out" >&2 || true
  exit 2
fi
echo "render_config: $out  (output_path=$newpath)"
