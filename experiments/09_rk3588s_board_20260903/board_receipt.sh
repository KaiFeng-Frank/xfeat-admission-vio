#!/bin/sh
# Board identity receipt for the RK3588S; runs inside `adb shell`. Read-only.
echo "== compatible =="; tr '\0' '\n' < /proc/device-tree/compatible 2>/dev/null; echo
echo "== model =="; tr '\0' '\n' < /proc/device-tree/model 2>/dev/null; echo
echo "== kernel =="; uname -a
echo "== os =="; cat /etc/os-release 2>/dev/null | head -3; getprop ro.build.fingerprint 2>/dev/null; getprop ro.product.model 2>/dev/null
echo "== user =="; id
echo "== cpu =="; grep -m1 -E "model name|CPU part" /proc/cpuinfo; grep -c processor /proc/cpuinfo; cat /sys/devices/system/cpu/cpu*/cpufreq/cpuinfo_max_freq 2>/dev/null | sort -u | tr '\n' ' '; echo
echo "== mem =="; grep -E "MemTotal|MemAvailable" /proc/meminfo
echo "== npu driver =="; cat /sys/kernel/debug/rknpu/version 2>/dev/null || dmesg 2>/dev/null | grep -i rknpu | head -3; ls -la /dev/rknpu* /dev/dri/renderD* 2>/dev/null
cat /sys/kernel/debug/rknpu/load 2>/dev/null; cat /sys/class/devfreq/fdab0000.npu/cur_freq 2>/dev/null
echo "== rknn runtime lib =="; for f in /usr/lib/librknnrt.so /usr/lib64/librknnrt.so /vendor/lib64/librknnrt.so /oem/usr/lib/librknnrt.so /usr/local/lib/librknnrt.so; do [ -f "$f" ] && { ls -la "$f"; strings "$f" 2>/dev/null | grep -m2 -E "librknnrt version|rknn_runtime version"; }; done
find / -name "librknnrt*.so*" -o -name "librknn_api*.so*" 2>/dev/null | head -5
echo "== python / rknnlite =="; for py in python3 python; do command -v $py >/dev/null 2>&1 && { $py --version 2>&1; $py -c "import rknnlite, sys; print('rknnlite', getattr(rknnlite,'__version__','?'))" 2>&1 | tail -1; $py -c "import numpy; print('numpy', numpy.__version__)" 2>&1 | tail -1; break; }; done
echo "== rknn_server / tools =="; ls /usr/bin/rknn_server /vendor/bin/rknn_server /usr/bin/rknn_benchmark* 2>/dev/null; command -v rknn_benchmark 2>/dev/null
echo "== network =="; ip -br addr 2>/dev/null || ifconfig 2>/dev/null | grep -E "inet |^[a-z]"
echo "== storage =="; df -h /data /userdata /home /tmp 2>/dev/null | tail -n +1
echo "== temp =="; for z in /sys/class/thermal/thermal_zone*; do [ -f "$z/temp" ] && echo "$(cat $z/type 2>/dev/null): $(cat $z/temp)"; done | head -8
