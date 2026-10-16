// Offline parity and latency check of the online extractor on recorded gray frames.
//
//   xfeat_online_check RELIABILITY_MODEL KEYPOINT_HEAD FRAMES OUT_PREFIX [cpu_threads] [npu_cores]
//
//   FRAMES             "XFGRAY01", uint32 n, then n x (int64 stamp_ns, uint8 gray[480*640])
//   OUT_PREFIX.xfs     XFSIDE01 sidecar, one record per frame (zero descriptors)
//   OUT_PREFIX.csv     per-frame timing of the threaded launch/collect path
//   OUT_PREFIX.frame0  frame 0's keypoint logits [4800][65] and reliability [4800], float32

#include "xfeat_online.h"

#include <chrono>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iostream>
#include <stdexcept>

using namespace xfeat_online;

static int run(int argc, char **argv);

int main(int argc, char **argv)
{
    try
    {
        return run(argc, argv);
    }
    catch (const std::exception &e)
    {
        std::cerr << "xfeat_online_check: " << e.what() << "\n";
        return 1;
    }
}

static int run(int argc, char **argv)
{
    if (argc < 5)
    {
        std::cerr << "usage: " << argv[0]
                  << " RELIABILITY_MODEL KEYPOINT_HEAD FRAMES OUT_PREFIX [cpu_threads] [npu_cores]\n";
        return 2;
    }
    const std::string model = argv[1], head_path = argv[2], frames_path = argv[3], prefix = argv[4];
    const int threads = argc > 5 ? std::atoi(argv[5]) : 1;
    const std::string cores = argc > 6 ? argv[6] : "0_1_2";

    std::ifstream frames(frames_path.c_str(), std::ios::in | std::ios::binary);
    char magic[8];
    uint32_t count = 0;
    frames.read(magic, 8);
    frames.read(reinterpret_cast<char *>(&count), 4);
    if (!frames || std::memcmp(magic, "XFGRAY01", 8) != 0)
        throw std::runtime_error("not an XFGRAY01 frame file: " + frames_path);

    std::ofstream xfs((prefix + ".xfs").c_str(), std::ios::out | std::ios::binary);
    std::ofstream csv((prefix + ".csv").c_str());
    const uint32_t header[6] = {1u, kWidth, kHeight, 64u, kProposalLimit, 0u};
    const uint64_t frame_count = count;
    xfs.write("XFSIDE01", 8);
    xfs.write(reinterpret_cast<const char *>(header), sizeof(header));
    xfs.write(reinterpret_cast<const char *>(&frame_count), sizeof(frame_count));
    csv << "frame,stamp_ns,proposals,keypoint_ms,heatmap_ms,reliability_ms,tail_ms,latency_ms\n";

    OnlineExtractor extractor(model, head_path, threads, cores);
    std::cerr << "backend: " << extractor.describe() << "\n";
    cv::Mat gray(kHeight, kWidth, CV_8UC1);
    Proposals proposals;
    Timing timing;
    std::vector<float> zeros(64, 0.0f);
    for (uint32_t f = 0; f < count; ++f)
    {
        int64_t stamp = 0;
        frames.read(reinterpret_cast<char *>(&stamp), 8);
        frames.read(reinterpret_cast<char *>(gray.data), kHeight * kWidth);
        if (!frames)
            throw std::runtime_error("truncated frame file");
        if (f == 0)
        {
            KeypointHead head(head_path);
            std::unique_ptr<ReliabilityBackend> backend = makeReliabilityBackend(model, threads, cores);
            std::vector<float> logits(static_cast<size_t>(kCells) * 65u), reliability(kCells);
            head.run(gray.data, logits.data());
            backend->run(gray.data, reliability.data());
            std::ofstream dump((prefix + ".frame0").c_str(), std::ios::out | std::ios::binary);
            dump.write(reinterpret_cast<const char *>(logits.data()), logits.size() * sizeof(float));
            dump.write(reinterpret_cast<const char *>(reliability.data()), reliability.size() * sizeof(float));
        }
        extractor.launch(gray);
        extractor.collect(proposals, timing);
        const uint32_t n = static_cast<uint32_t>(proposals.points.size());
        xfs.write(reinterpret_cast<const char *>(&stamp), 8);
        xfs.write(reinterpret_cast<const char *>(&n), 4);
        for (uint32_t i = 0; i < n; ++i)
        {
            const float xys[3] = {proposals.points[i].x, proposals.points[i].y, proposals.scores[i]};
            xfs.write(reinterpret_cast<const char *>(xys), sizeof(xys));
            xfs.write(reinterpret_cast<const char *>(zeros.data()), 64 * sizeof(float));
        }
        char row[256];
        std::snprintf(row, sizeof(row), "%u,%lld,%u,%.3f,%.3f,%.3f,%.3f,%.3f\n", f, static_cast<long long>(stamp), n,
                      timing.keypoint_ms, timing.heatmap_ms, timing.reliability_ms, timing.tail_ms, timing.latency_ms);
        csv << row;
    }
    std::cerr << "frames: " << count << " -> " << prefix << ".xfs\n";
    return 0;
}
