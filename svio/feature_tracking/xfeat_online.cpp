// Compiled with -ffp-contract=off: the tail reproduces the pinned float32
// arithmetic operation by operation (sampling coordinates, bilinear weights,
// score products), which a fused multiply-add would round differently.

#include "xfeat_online.h"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstring>
#include <fstream>
#include <limits>
#include <stdexcept>

namespace xfeat_online
{

#ifdef SVIO_XFEAT_RKNN
std::unique_ptr<ReliabilityBackend> makeRknnBackend(const std::string &model_path, const std::string &npu_cores);
#endif
#ifdef SVIO_XFEAT_ONNXRUNTIME
std::unique_ptr<ReliabilityBackend> makeOnnxBackend(const std::string &model_path, int cpu_threads);
#endif

std::unique_ptr<ReliabilityBackend> makeReliabilityBackend(const std::string &model_path,
                                                           int cpu_threads,
                                                           const std::string &npu_cores)
{
    auto ends_with = [&model_path](const std::string &suffix)
    {
        return model_path.size() >= suffix.size() &&
               model_path.compare(model_path.size() - suffix.size(), suffix.size(), suffix) == 0;
    };
    if (ends_with(".rknn"))
    {
#ifdef SVIO_XFEAT_RKNN
        return makeRknnBackend(model_path, npu_cores);
#else
        throw std::runtime_error("this build has no RKNN backend (configure with -DSVIO_XFEAT_RKNN=ON): " + model_path);
#endif
    }
    if (ends_with(".onnx"))
    {
#ifdef SVIO_XFEAT_ONNXRUNTIME
        return makeOnnxBackend(model_path, cpu_threads);
#else
        throw std::runtime_error("this build has no onnxruntime backend (configure with -DSVIO_XFEAT_ONNXRUNTIME_ROOT=...): " + model_path);
#endif
    }
    (void)cpu_threads;
    (void)npu_cores;
    throw std::runtime_error("reliability model must be .rknn or .onnx: " + model_path);
}

// ---------------------------------------------------------------------------
// Keypoint head

namespace
{
template <typename T>
void readExactly(std::ifstream &in, T *data, size_t count, const std::string &path)
{
    in.read(reinterpret_cast<char *>(data), static_cast<std::streamsize>(count * sizeof(T)));
    if (!in)
        throw std::runtime_error("truncated keypoint head weights: " + path);
}

double nowSeconds()
{
    return std::chrono::duration<double>(std::chrono::steady_clock::now().time_since_epoch()).count();
}
}  // namespace

KeypointHead::KeypointHead(const std::string &weights_path)
{
    std::ifstream in(weights_path.c_str(), std::ios::in | std::ios::binary);
    if (!in)
        throw std::runtime_error("cannot open keypoint head weights: " + weights_path);
    char magic[8];
    uint32_t header[3];
    readExactly(in, magic, 8, weights_path);
    readExactly(in, header, 3, weights_path);
    readExactly(in, &eps_, 1, weights_path);
    if (std::memcmp(magic, "XFKHEAD1", 8) != 0 || header[0] != 1u || header[1] != 64u || header[2] != 65u)
        throw std::runtime_error("unsupported keypoint head weights: " + weights_path);
    for (int k = 0; k < 3; ++k)
    {
        readExactly(in, w_[k].data(), 64 * 64, weights_path);
        readExactly(in, b_[k].data(), 64, weights_path);
    }
    readExactly(in, w3_.data(), 65 * 64, weights_path);
    readExactly(in, b3_.data(), 65, weights_path);
    if (in.peek() != std::char_traits<char>::eof())
        throw std::runtime_error("trailing bytes in keypoint head weights: " + weights_path);
    x_.resize(64, kCells);
    h_.resize(64, kCells);
}

void KeypointHead::run(const uint8_t *gray, float *logits)
{
    // Instance norm of the whole gray frame (statistics in float64), then the
    // 8x8 unfold: column = cell 80*cy + cx, row = 8*dy + dx.
    std::array<uint64_t, 256> histogram{};
    for (int i = 0; i < kHeight * kWidth; ++i)
        ++histogram[gray[i]];
    const double n = static_cast<double>(kHeight * kWidth);
    double sum = 0.0;
    for (int v = 0; v < 256; ++v)
        sum += static_cast<double>(v) * static_cast<double>(histogram[v]);
    const double mean = sum / n;
    double squares = 0.0;
    for (int v = 0; v < 256; ++v)
        squares += (v - mean) * (v - mean) * static_cast<double>(histogram[v]);
    const double inv_std = 1.0 / std::sqrt(squares / n + static_cast<double>(eps_));
    std::array<float, 256> normalized;
    for (int v = 0; v < 256; ++v)
        normalized[v] = static_cast<float>((v - mean) * inv_std);

    for (int cy = 0; cy < kCellsY; ++cy)
        for (int cx = 0; cx < kCellsX; ++cx)
        {
            float *column = x_.col(cy * kCellsX + cx).data();
            for (int dy = 0; dy < 8; ++dy)
            {
                const uint8_t *row = gray + (8 * cy + dy) * kWidth + 8 * cx;
                for (int dx = 0; dx < 8; ++dx)
                    column[8 * dy + dx] = normalized[row[dx]];
            }
        }

    h_.noalias() = w_[0] * x_;
    h_ = (h_.colwise() + b_[0]).cwiseMax(0.0f);
    x_.noalias() = w_[1] * h_;
    x_ = (x_.colwise() + b_[1]).cwiseMax(0.0f);
    h_.noalias() = w_[2] * x_;
    h_ = (h_.colwise() + b_[2]).cwiseMax(0.0f);
    Eigen::Map<Eigen::Matrix<float, 65, Eigen::Dynamic>> out(logits, 65, kCells);
    out.noalias() = w3_ * h_;
    out.colwise() += b3_;
}

// ---------------------------------------------------------------------------
// Sparse tail

namespace
{
// InterpolateSparse2d normgrid + grid_sample(align_corners=False), float32.
inline float gridSource(float coordinate, int source_size, int original_size)
{
    const float normalized = 2.0f * (coordinate / static_cast<float>(original_size - 1)) - 1.0f;
    return ((normalized + 1.0f) * static_cast<float>(source_size) - 1.0f) * 0.5f;
}

inline float gatherZero(const float *tensor, int height, int width, long x, long y)
{
    if (x < 0 || x >= width || y < 0 || y >= height)
        return 0.0f;
    return tensor[y * width + x];
}
}  // namespace

void SparseTail::heatmap(const float *logits)
{
    // 65-way cell softmax, dustbin dropped, 8x pixel shuffle.
    heat_.resize(kHeight * kWidth);
    for (int cell = 0; cell < kCells; ++cell)
    {
        const float *l = logits + static_cast<size_t>(cell) * 65u;
        float peak = l[0];
        for (int c = 1; c < 65; ++c)
            peak = std::max(peak, l[c]);
        float e[65];
        float total = 0.0f;
        for (int c = 0; c < 65; ++c)
        {
            e[c] = std::exp(l[c] - peak);
            total += e[c];
        }
        const int cy = cell / kCellsX, cx = cell % kCellsX;
        for (int c = 0; c < 64; ++c)
            heat_[(8 * cy + c / 8) * kWidth + 8 * cx + c % 8] = e[c] / total;
    }

    // 5x5 max-pool NMS with -inf outside the image, threshold 0.05: a pixel is
    // kept iff it exceeds the threshold and no pixel of its 5x5 window is larger
    // (equal to the window max). Only above-threshold pixels are examined.
    const float threshold = 0.05f;
    candidates_.clear();
    for (int y = 0; y < kHeight; ++y)
    {
        const float *row = heat_.data() + y * kWidth;
        for (int x = 0; x < kWidth; ++x)
        {
            const float h = row[x];
            if (!(h > threshold))
                continue;
            bool peak = true;
            for (int yy = std::max(0, y - 2); peak && yy <= std::min(kHeight - 1, y + 2); ++yy)
            {
                const float *r = heat_.data() + yy * kWidth;
                for (int xx = std::max(0, x - 2); xx <= std::min(kWidth - 1, x + 2); ++xx)
                    if (r[xx] > h)
                    {
                        peak = false;
                        break;
                    }
            }
            if (peak)
                candidates_.push_back(y * kWidth + x);
        }
    }
}

void SparseTail::score(const float *reliability, Proposals &out)
{
    // score = nearest(heat) x bilinear(reliability); (0,0) is upstream's padding
    // sentinel; only scores > 0 survive.
    points_.clear();
    scores_.clear();
    for (const int index : candidates_)
    {
        const int y = index / kWidth, x = index % kWidth;
        const float fx = static_cast<float>(x), fy = static_cast<float>(y);
        const long nx = std::lrint(gridSource(fx, kWidth, kWidth));
        const long ny = std::lrint(gridSource(fy, kHeight, kHeight));
        const float heat_score = gatherZero(heat_.data(), kHeight, kWidth, nx, ny);

        const float sx = gridSource(fx, kCellsX, kWidth);
        const float sy = gridSource(fy, kCellsY, kHeight);
        const long x0 = static_cast<long>(std::floor(sx)), y0 = static_cast<long>(std::floor(sy));
        const float wx1 = sx - static_cast<float>(x0), wy1 = sy - static_cast<float>(y0);
        const float wx0 = 1.0f - wx1, wy0 = 1.0f - wy1;
        const float t00 = gatherZero(reliability, kCellsY, kCellsX, x0, y0) * (wx0 * wy0);
        const float t10 = gatherZero(reliability, kCellsY, kCellsX, x0 + 1, y0) * (wx1 * wy0);
        const float t01 = gatherZero(reliability, kCellsY, kCellsX, x0, y0 + 1) * (wx0 * wy1);
        const float t11 = gatherZero(reliability, kCellsY, kCellsX, x0 + 1, y0 + 1) * (wx1 * wy1);
        const float reliability_score = ((t00 + t10) + t01) + t11;

        float score = heat_score * reliability_score;
        if (x == 0 && y == 0)
            score = -1.0f;
        if (!(score > 0.0f))
            continue;
        points_.push_back(cv::Point2f(fx, fy));
        scores_.push_back(score);
    }

    // Rank by (-score, x, y), keep 500.
    order_.resize(points_.size());
    for (size_t i = 0; i < order_.size(); ++i)
        order_[i] = static_cast<int>(i);
    std::sort(order_.begin(), order_.end(), [this](int a, int b)
              {
                  if (scores_[a] != scores_[b])
                      return scores_[a] > scores_[b];
                  if (points_[a].x != points_[b].x)
                      return points_[a].x < points_[b].x;
                  return points_[a].y < points_[b].y;
              });
    const size_t keep = std::min<size_t>(order_.size(), kProposalLimit);
    out.points.resize(keep);
    out.scores.resize(keep);
    for (size_t i = 0; i < keep; ++i)
    {
        out.points[i] = points_[order_[i]];
        out.scores[i] = scores_[order_[i]];
    }
}

// ---------------------------------------------------------------------------
// Extractor

OnlineExtractor::OnlineExtractor(const std::string &reliability_model, const std::string &keypoint_head,
                                 int cpu_threads, const std::string &npu_cores)
    : backend_(makeReliabilityBackend(reliability_model, cpu_threads, npu_cores)),
      head_(keypoint_head),
      gray_(kHeight * kWidth),
      logits_(static_cast<size_t>(kCells) * 65u),
      reliability_(kCells)
{
    reliability_thread_ = std::thread(&OnlineExtractor::reliabilityLoop, this);
    keypoint_thread_ = std::thread(&OnlineExtractor::keypointLoop, this);
}

OnlineExtractor::~OnlineExtractor()
{
    {
        std::lock_guard<std::mutex> lock(mutex_);
        stop_ = true;
    }
    cv_.notify_all();
    reliability_thread_.join();
    keypoint_thread_.join();
}

void OnlineExtractor::launch(const cv::Mat &gray)
{
    if (gray.type() != CV_8UC1 || gray.rows != kHeight || gray.cols != kWidth)
        throw std::runtime_error("online XFeat expects a 640x480 8-bit gray frame");
    std::unique_lock<std::mutex> lock(mutex_);
    cv_.wait(lock, [this] { return done_ == launched_; });
    for (int r = 0; r < kHeight; ++r)
        std::memcpy(gray_.data() + r * kWidth, gray.ptr<uint8_t>(r), kWidth);
    error_.clear();
    launch_s_ = nowSeconds();
    ++launched_;
    lock.unlock();
    cv_.notify_all();
}

void OnlineExtractor::collect(Proposals &out, Timing &timing)
{
    std::unique_lock<std::mutex> lock(mutex_);
    if (launched_ == 0)
        throw std::logic_error("online XFeat: collect() without launch()");
    cv_.wait(lock, [this] { return done_ == launched_; });
    if (!error_.empty())
        throw std::runtime_error("online XFeat: " + error_);
    out = result_;
    timing = timing_;
}

void OnlineExtractor::reliabilityLoop()
{
    uint64_t job = 0;
    for (;;)
    {
        {
            std::unique_lock<std::mutex> lock(mutex_);
            cv_.wait(lock, [&] { return stop_ || launched_ > job; });
            if (stop_)
                return;
            job = launched_;
        }
        const double t0 = nowSeconds();
        std::string error;
        try
        {
            backend_->run(gray_.data(), reliability_.data());
        }
        catch (const std::exception &e)
        {
            error = e.what();
        }
        {
            std::lock_guard<std::mutex> lock(mutex_);
            timing_.reliability_ms = 1e3 * (nowSeconds() - t0);
            if (!error.empty())
                error_ = error;
            reliability_done_ = job;
        }
        cv_.notify_all();
    }
}

void OnlineExtractor::keypointLoop()
{
    uint64_t job = 0;
    for (;;)
    {
        {
            std::unique_lock<std::mutex> lock(mutex_);
            cv_.wait(lock, [&] { return stop_ || launched_ > job; });
            if (stop_)
                return;
            job = launched_;
        }
        const double t0 = nowSeconds();
        head_.run(gray_.data(), logits_.data());
        const double t1 = nowSeconds();
        tail_.heatmap(logits_.data());
        const double t2 = nowSeconds();
        {
            std::unique_lock<std::mutex> lock(mutex_);
            cv_.wait(lock, [&] { return stop_ || reliability_done_ == job; });
            if (stop_)
                return;
        }
        const double t3 = nowSeconds();
        bool ok;
        {
            std::lock_guard<std::mutex> lock(mutex_);
            ok = error_.empty();
        }
        if (ok)
            tail_.score(reliability_.data(), result_);
        else
            result_ = Proposals();
        const double t4 = nowSeconds();
        {
            std::lock_guard<std::mutex> lock(mutex_);
            timing_.keypoint_ms = 1e3 * (t1 - t0);
            timing_.heatmap_ms = 1e3 * (t2 - t1);
            timing_.tail_ms = 1e3 * (t4 - t3);
            timing_.latency_ms = 1e3 * (t4 - launch_s_);
            done_ = job;
        }
        cv_.notify_all();
    }
}

}  // namespace xfeat_online
