#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source "$script_dir/frozen_contract.sh"

# OFF is defined by absence, not by an alternate value. Clear every present
# and future SVIO_XFEAT_* variable, then fail closed if anything survived.
clear_xfeat_environment
assert_xfeat_environment_empty
exec "$script_dir/run_sequence_common.sh" off "$@"
