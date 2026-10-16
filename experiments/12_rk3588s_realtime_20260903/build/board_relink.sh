#!/bin/bash
# The board clock lagged the host by three months, so the freshly compiled objects looked
# older than the QEMU-built link outputs and make skipped the link. Clock is set from the host
# before this runs; remove the stale outputs and let catkin_make relink.
set -o pipefail
export ROS_MASTER_URI=http://127.0.0.1:11311 ROS_HOSTNAME=127.0.0.1 HOME=/root
source /opt/ros/noetic/setup.bash
cd /opt/svio_ws
date
rm -f devel/lib/libsvio.so devel/lib/svio/svio_syn_node devel/lib/svio/svio_stereo_node
find build/SVIO/svio -name "*.o" -newer src/SVIO/svio/state_estimation/svio_syn_node.cpp | wc -l
taskset -c 4-7 catkin_make -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_FLAGS=-mcpu=cortex-a76 "-DCMAKE_CXX_FLAGS_RELWITHDEBINFO=-O3 -DNDEBUG" -j4 > /data/board_relink.log 2>&1
echo "CATKIN_EXIT=$?"
grep -E "Linking|Building CXX" /data/board_relink.log | cut -c1-100
ls -la --time-style=full-iso devel/lib/libsvio.so devel/lib/svio/svio_syn_node
sha256sum devel/lib/svio/svio_syn_node devel/lib/libsvio.so
python3 -c "print('strings backend_freq_gate:', open('devel/lib/svio/svio_syn_node','rb').read().count(b'backend_freq_gate'), open('devel/lib/libsvio.so','rb').read().count(b'backend_freq_gate'))"
