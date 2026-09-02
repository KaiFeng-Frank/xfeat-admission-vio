// Sandbox-only, no-GT reproduction of the frozen S-VIO FeatureTracker OFF path.
//
// Input is a stream of raw 640x480 BGR frames.  This worker is compiled and
// run inside the estimator's Ubuntu 20.04/OpenCV 4.2 image.  It deliberately
// contains no XFeat code: it observes the KLT survivor count at the exact
// admission point before either XFeat or Shi-Tomasi could add new identities.

#include <algorithm>
#include <array>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <opencv2/calib3d.hpp>
#include <opencv2/core.hpp>
#include <opencv2/imgproc.hpp>
#include <opencv2/video/tracking.hpp>

namespace {

constexpr int kWidth = 640;
constexpr int kHeight = 480;
constexpr int kChannels = 3;
constexpr int kMaxCount = 150;
constexpr int kMinDistance = 20;
constexpr double kFThreshold = 2.0;
constexpr double kFocalLength = 460.0;
constexpr double kFx = 4.59357e+02;
constexpr double kFy = 4.59764e+02;
constexpr double kCx = 3.32695e+02;
constexpr double kCy = 2.58998e+02;
constexpr int kBorderSize = 1;
constexpr std::array<char, 8> kMagic = {'V', 'C', 'U', 'L', 'G', 'T', '0', '1'};

template <typename T>
bool readValue(std::istream& stream, T& value) {
    stream.read(reinterpret_cast<char*>(&value), sizeof(T));
    if (stream) return true;
    if (stream.eof() && stream.gcount() == 0) return false;
    throw std::runtime_error("truncated input stream");
}

void readExact(std::istream& stream, char* data, std::streamsize bytes,
               const char* label) {
    stream.read(data, bytes);
    if (!stream) throw std::runtime_error(std::string("truncated ") + label);
}

template <typename T>
void reduceVector(std::vector<T>& values, const std::vector<uchar>& status) {
    int out = 0;
    for (int i = 0; i < static_cast<int>(values.size()); ++i) {
        if (status[i]) values[out++] = values[i];
    }
    values.resize(out);
}

bool inBorder(const cv::Point2f& point) {
    const int x = cvRound(point.x);
    const int y = cvRound(point.y);
    return kBorderSize <= x && x < kWidth - kBorderSize &&
           kBorderSize <= y && y < kHeight - kBorderSize;
}

cv::Point2f focalPlanePoint(const cv::Point2f& point) {
    // Exact zero-distortion PINHOLE liftProjective algebra from the frozen
    // camera model, followed by FeatureTracker::rejectWithF's 460 px plane.
    const double mx = (1.0 / kFx) * point.x - kCx / kFx;
    const double my = (1.0 / kFy) * point.y - kCy / kFy;
    return cv::Point2f(
        static_cast<float>(kFocalLength * mx + kWidth / 2.0),
        static_cast<float>(kFocalLength * my + kHeight / 2.0));
}

struct Tracker {
    cv::Mat previous_gray;
    std::vector<cv::Point2f> previous_points;
    std::vector<cv::Point2f> current_points;
    std::vector<int> ids;
    std::vector<int> ages;
    int next_id = 0;

    struct Observation {
        int lk_border_survivors = 0;
        int f_survivors = 0;
        int spaced_survivors = 0;
        int deficit = kMaxCount;
        int added_shi_tomasi = 0;
    };

    Observation process(const cv::Mat& gray) {
        current_points.clear();
        if (!previous_points.empty()) {
            std::vector<uchar> status;
            std::vector<float> error;
            cv::calcOpticalFlowPyrLK(previous_gray, gray, previous_points,
                                     current_points, status, error,
                                     cv::Size(21, 21), 3);
            for (int i = 0; i < static_cast<int>(current_points.size()); ++i) {
                if (status[i] && !inBorder(current_points[i])) status[i] = 0;
            }
            reduceVector(previous_points, status);
            reduceVector(current_points, status);
            reduceVector(ids, status);
            reduceVector(ages, status);
        }

        Observation observation;
        observation.lk_border_survivors = static_cast<int>(current_points.size());
        for (int& age : ages) ++age;

        if (previous_points.size() >= 8) {
            std::vector<cv::Point2f> un_previous(previous_points.size());
            std::vector<cv::Point2f> un_current(current_points.size());
            for (std::size_t i = 0; i < previous_points.size(); ++i) {
                un_previous[i] = focalPlanePoint(previous_points[i]);
                un_current[i] = focalPlanePoint(current_points[i]);
            }
            std::vector<uchar> status;
            cv::findFundamentalMat(un_previous, un_current, cv::FM_RANSAC,
                                   kFThreshold, 0.99, status);
            // Frozen rejectWithF unconditionally consumes OpenCV's status.
            reduceVector(previous_points, status);
            reduceVector(current_points, status);
            reduceVector(ids, status);
            reduceVector(ages, status);
        }
        observation.f_survivors = static_cast<int>(current_points.size());

        // Byte-for-source-shape reproduction of FeatureTracker::setMask:
        // std::sort (not stable_sort), age descending, same nested pair type.
        cv::Mat mask(kHeight, kWidth, CV_8UC1, cv::Scalar(255));
        std::vector<std::pair<int, std::pair<cv::Point2f, int>>> ranked;
        ranked.reserve(current_points.size());
        for (std::size_t i = 0; i < current_points.size(); ++i) {
            ranked.push_back(std::make_pair(
                ages[i], std::make_pair(current_points[i], ids[i])));
        }
        std::sort(ranked.begin(), ranked.end(),
                  [](const std::pair<int, std::pair<cv::Point2f, int>>& a,
                     const std::pair<int, std::pair<cv::Point2f, int>>& b) {
                      return a.first > b.first;
                  });
        current_points.clear();
        ids.clear();
        ages.clear();
        for (auto& item : ranked) {
            if (mask.at<uchar>(item.second.first) == 255) {
                current_points.push_back(item.second.first);
                ids.push_back(item.second.second);
                ages.push_back(item.first);
                cv::circle(mask, item.second.first, kMinDistance, 0, -1);
            }
        }
        observation.spaced_survivors = static_cast<int>(current_points.size());
        observation.deficit = kMaxCount - observation.spaced_survivors;

        std::vector<cv::Point2f> new_points;
        if (observation.deficit > 0) {
            cv::goodFeaturesToTrack(gray, new_points, observation.deficit,
                                    0.01, kMinDistance, mask);
        }
        observation.added_shi_tomasi = static_cast<int>(new_points.size());
        for (const cv::Point2f& point : new_points) {
            current_points.push_back(point);
            ids.push_back(next_id++);
            ages.push_back(1);
        }

        previous_gray = gray.clone();
        previous_points.swap(current_points);
        return observation;
    }
};

std::string argument(int argc, char** argv, const std::string& name) {
    for (int i = 1; i + 1 < argc; ++i) {
        if (argv[i] == name) return argv[i + 1];
    }
    throw std::runtime_error("missing argument: " + name);
}

}  // namespace

int main(int argc, char** argv) {
    try {
        const std::string sequence = argument(argc, argv, "--sequence");
        const std::string output_path = argument(argc, argv, "--out");
        if (sequence != "light1" && sequence != "light3" && sequence != "light5")
            throw std::runtime_error("sequence is outside the light1/light3/light5 allowlist");

        std::array<char, 8> magic{};
        readExact(std::cin, magic.data(), magic.size(), "stream magic");
        std::uint32_t width = 0, height = 0, channels = 0;
        if (!readValue(std::cin, width) || !readValue(std::cin, height) ||
            !readValue(std::cin, channels))
            throw std::runtime_error("truncated stream header");
        if (magic != kMagic || width != kWidth || height != kHeight ||
            channels != kChannels)
            throw std::runtime_error("unsupported RGB stream ABI");

        std::ofstream output(output_path);
        if (!output) throw std::runtime_error("cannot create output CSV");
        output << "sequence,frame_index,stamp_ns,tick,initialization,"
                  "lk_border_survivors,f_survivors,spaced_survivors,deficit,"
                  "shi_tomasi_added,post_fill_count\n";

        Tracker tracker;
        std::int64_t previous_stamp = -1;
        std::uint64_t frame_index = 0;
        while (true) {
            std::int64_t stamp_ns = 0;
            if (!readValue(std::cin, stamp_ns)) break;
            std::uint32_t payload_bytes = 0;
            if (!readValue(std::cin, payload_bytes))
                throw std::runtime_error("truncated frame header");
            if (payload_bytes != static_cast<std::uint32_t>(kWidth * kHeight * kChannels))
                throw std::runtime_error("unexpected BGR payload size");
            if (previous_stamp >= 0 && stamp_ns <= previous_stamp)
                throw std::runtime_error("non-increasing RGB header stamps");
            std::vector<uchar> payload(payload_bytes);
            readExact(std::cin, reinterpret_cast<char*>(payload.data()),
                      payload.size(), "BGR frame");
            cv::Mat bgr(kHeight, kWidth, CV_8UC3, payload.data());
            cv::Mat gray;
            cv::cvtColor(bgr, gray, cv::COLOR_BGR2GRAY);
            const Tracker::Observation observation = tracker.process(gray);
            const bool tick = (frame_index % 3u) == 0u;
            if (tick) {
                output << sequence << ',' << frame_index << ',' << stamp_ns
                       << ",1," << (frame_index == 0 ? 1 : 0) << ','
                       << observation.lk_border_survivors << ','
                       << observation.f_survivors << ','
                       << observation.spaced_survivors << ','
                       << observation.deficit << ','
                       << observation.added_shi_tomasi << ','
                       << (observation.spaced_survivors + observation.added_shi_tomasi)
                       << '\n';
            }
            previous_stamp = stamp_ns;
            ++frame_index;
        }
        if (frame_index == 0) throw std::runtime_error("empty RGB stream");
        std::cerr << "census " << sequence << ": " << frame_index
                  << " frames, " << ((frame_index + 2) / 3) << " ticks\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "fatal: " << error.what() << '\n';
        return 2;
    }
}
