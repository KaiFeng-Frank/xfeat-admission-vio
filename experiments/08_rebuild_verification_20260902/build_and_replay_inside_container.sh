#!/usr/bin/env bash
set -o pipefail
export ROS_MASTER_URI=http://127.0.0.1:11311 ROS_HOSTNAME=127.0.0.1
export DEBIAN_FRONTEND=noninteractive
echo "== apt libceres-dev =="
apt-get update -qq > /work/apt.log 2>&1 && apt-get install -y -qq libceres-dev >> /work/apt.log 2>&1; echo APT_EXIT=$?
dpkg -l libceres-dev libceres1 2>/dev/null | tail -2
ls -la /usr/lib/x86_64-linux-gnu/libceres* ; sha256sum /usr/lib/x86_64-linux-gnu/libceres.so.1.14.0 /usr/lib/x86_64-linux-gnu/libceres.so.1 2>/dev/null
source /opt/ros/noetic/setup.bash
cd /work/svio_ws && rm -rf build devel
echo "== catkin_make =="
catkin_make -DCMAKE_BUILD_TYPE=Release -j16 > /work/svio_ws/catkin_make.log 2>&1; echo BUILD_EXIT=$?
tail -3 /work/svio_ws/catkin_make.log
sha256sum /work/svio_ws/devel/lib/svio/svio_syn_node /work/svio_ws/devel/lib/libsvio.so 2>&1
if [[ -x /work/svio_ws/devel/lib/svio/svio_syn_node ]]; then
  echo "== replay ON =="; bash /work/verify/run_light1_verify.sh on 11611
  echo "== replay OFF =="; bash /work/verify/run_light1_verify.sh off 11612
fi
chown -R 1000:1000 /work
echo "== done =="
