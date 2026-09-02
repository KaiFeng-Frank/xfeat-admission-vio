#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
source "$script_dir/frozen_contract.sh"

# Remove inherited experimental knobs; the common runner injects exactly the
# frozen admission pair after the local XFS ABI check.
clear_xfeat_environment
exec "$script_dir/run_sequence_common.sh" learned "$@"
