#pragma once

// Online, on-demand, admission-only XFeat proposals.
//
// Admission reads only (x, y, score) of each proposal, with score = K x R: the
// keypoint heat map K (65-way cell softmax of the keypoint branch) sampled at its
// own 5x5 NMS maxima, times the backbone reliability R sampled bilinearly there.
// The extractor therefore computes exactly two things per launched frame:
//   R  the backbone + reliability head on the gray frame (ReliabilityBackend:
//      RKNN on the RK3588 NPU, onnxruntime on a desktop), no descriptor head;
//   K  the keypoint branch (instance norm, 8x8 unfold, four 1x1 convolutions)
//      on the CPU in float32,
// concurrently, then the pinned sparse tail without descriptors. The output is the
// sealed sidecar's proposal list for that frame (same NMS, threshold, sampling,
// ranking, 500 cap), with zero descriptors.

#include <condition_variable>
#include <cstdint>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include <eigen3/Eigen/Dense>
#include <opencv2/core/core.hpp>

namespace xfeat_online
{

constexpr int kHeight = 480;
constexpr int kWidth = 640;
constexpr int kCellsY = kHeight / 8;
constexpr int kCellsX = kWidth / 8;
constexpr int kCells = kCellsY * kCellsX;
constexpr int kProposalLimit = 500;

// gray uint8 [480*640] -> reliability float32 [60*80]
class ReliabilityBackend
{
public:
    virtual ~ReliabilityBackend() = default;
    virtual void run(const uint8_t *gray, float *reliability) = 0;
    virtual std::string describe() const = 0;
};

// Chooses the backend from the model file extension (.rknn or .onnx); throws if
// this build does not carry that backend.
std::unique_ptr<ReliabilityBackend> makeReliabilityBackend(const std::string &model_path,
                                                           int cpu_threads,
                                                           const std::string &npu_cores);

class KeypointHead
{
public:
    explicit KeypointHead(const std::string &weights_path);
    // logits: cell-major [4800][65] (cell = 80 * cy + cx)
    void run(const uint8_t *gray, float *logits);

private:
    float eps_ = 0.0f;
    Eigen::Matrix<float, 64, 64, Eigen::RowMajor> w_[3];
    Eigen::Matrix<float, 65, 64, Eigen::RowMajor> w3_;
    Eigen::Matrix<float, 64, 1> b_[3];
    Eigen::Matrix<float, 65, 1> b3_;
    Eigen::Matrix<float, 64, Eigen::Dynamic> x_, h_;
};

struct Proposals
{
    std::vector<cv::Point2f> points;  // score-ranked, at most 500
    std::vector<float> scores;
};

// The pinned sparse post-processing (sidecar/pinned/xfeat_sparse_onnx.py,
// sparse_from_backbone) without descriptors, in two steps: heatmap() needs only
// K (cell softmax, NMS, threshold) and runs while the backbone is still on the
// NPU; score() then samples R at the candidates and ranks them.
class SparseTail
{
public:
    void heatmap(const float *logits);
    void score(const float *reliability, Proposals &out);

private:
    std::vector<float> heat_;
    std::vector<int> candidates_, order_;
    std::vector<cv::Point2f> points_;
    std::vector<float> scores_;
};

struct Timing
{
    double keypoint_ms = 0.0;     // CPU keypoint head
    double heatmap_ms = 0.0;      // cell softmax + NMS (overlaps the backbone)
    double reliability_ms = 0.0;  // backend call, application visible
    double tail_ms = 0.0;         // R sampling + ranking, after both
    double latency_ms = 0.0;      // launch -> proposals ready
};

// Two worker threads: one drives the reliability backend, one runs the keypoint
// head and the heat map, then scores the candidates once R is in. launch() returns at once; collect() blocks
// until that frame's proposals are ready. A launched frame whose proposals are not
// needed is simply never collected; the next launch waits for it to finish.
class OnlineExtractor
{
public:
    OnlineExtractor(const std::string &reliability_model, const std::string &keypoint_head,
                    int cpu_threads, const std::string &npu_cores);
    ~OnlineExtractor();
    OnlineExtractor(const OnlineExtractor &) = delete;
    OnlineExtractor &operator=(const OnlineExtractor &) = delete;

    void launch(const cv::Mat &gray);
    void collect(Proposals &out, Timing &timing);
    std::string describe() const { return backend_->describe(); }

private:
    void reliabilityLoop();
    void keypointLoop();

    std::unique_ptr<ReliabilityBackend> backend_;
    KeypointHead head_;
    SparseTail tail_;
    std::vector<uint8_t> gray_;
    std::vector<float> logits_, reliability_;
    Proposals result_;
    Timing timing_;
    double launch_s_ = 0.0;
    std::string error_;  // backend failure of the current frame, rethrown by collect()

    std::mutex mutex_;
    std::condition_variable cv_;
    uint64_t launched_ = 0, reliability_done_ = 0, done_ = 0;
    bool stop_ = false;
    std::thread reliability_thread_, keypoint_thread_;
};

}  // namespace xfeat_online
