#!/usr/bin/env bash
# board_run.sh NAME ARM PORT [SEQ BAG EXPECT_FRAMES] — 1x replay, real-time config, estimator pinned to the A76
# cluster, new workspace in /dev/shm/xfeat_online/ws (1.4 native-build flags plus -g0).
set -uo pipefail
name=$1; arm=$2; port=$3; seq=${4:-light1}; bag=${5:-/data/vcu/light1.bag}; frames=${6:-2875}
X=/dev/shm/xfeat_online
export SVIO_WS=$X/ws SVIO_BASE_CONFIG=/opt/xfeat/config/base_realtime.yaml
export SVIO_PLAY_RATE=1.0 SVIO_DRAIN_STABLE=20 SVIO_EXPECT_FRAMES=$frames SVIO_EST_CORES=4-7
export SVIO_ONLINE_MODEL=$X/models/reliability_gray_fp16.rknn SVIO_ONLINE_KHEAD=$X/models/keypoint_head_fp32.bin
rm -rf /data/runs/$name
/opt/xfeat/bin/svio-chroot.sh bash $X/run_estimator.sh $seq $arm $port $bag "" /data/runs/$name > $X/$name.shell.log 2>&1
echo "RUN_EXIT=$?" >> $X/$name.shell.log
