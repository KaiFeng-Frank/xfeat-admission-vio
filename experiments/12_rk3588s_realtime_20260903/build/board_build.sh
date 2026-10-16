#!/bin/bash
# Native rebuild of the estimator inside the chroot with the patched sources and the board-tuned flags.
set -o pipefail
export ROS_MASTER_URI=http://127.0.0.1:11311 ROS_HOSTNAME=127.0.0.1 HOME=/root
source /opt/ros/noetic/setup.bash
cd /opt/svio_ws
rm -rf src/SVIO/svio && tar xzf /data/svio_src_patched.tgz -C src/SVIO/ && chown -R root:root src/SVIO/svio
echo "BUILD_START $(date +%s)"
taskset -c 4-7 catkin_make -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_FLAGS=-mcpu=cortex-a76 "-DCMAKE_CXX_FLAGS_RELWITHDEBINFO=-O3 -DNDEBUG" -j4 > /data/board_build.log 2>&1
echo "CATKIN_EXIT=$? BUILD_END $(date +%s)"
grep -c "error" /data/board_build.log
grep -m3 -i " error\|Error " /data/board_build.log
sha256sum devel/lib/svio/svio_syn_node devel/lib/libsvio.so
grep -o "mcpu=cortex-a76" build/SVIO/svio/CMakeFiles/svio_syn_node.dir/flags.make 2>/dev/null | head -1
grep -h "CXX_FLAGS" build/SVIO/svio/CMakeFiles/svio_syn_node.dir/flags.make 2>/dev/null | head -2
