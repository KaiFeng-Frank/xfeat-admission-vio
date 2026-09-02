#include "feature_tracker.h"

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <stdexcept>

bool FeatureTracker::inBorder(const cv::Point2f &pt)
{
    const int BORDER_SIZE = 1;
    int img_x = cvRound(pt.x);
    int img_y = cvRound(pt.y);
    return BORDER_SIZE <= img_x && img_x < col - BORDER_SIZE && BORDER_SIZE <= img_y && img_y < row - BORDER_SIZE;
}

void FeatureTracker::reduceVector(vector<cv::Point2f> &v, vector<uchar>& status)
{
    int j = 0;
    for (int i = 0; i < int(v.size()); i++)
        if (status[i])
            v[j++] = v[i];
    v.resize(j);
}

void FeatureTracker::reduceVector(vector<int> &v, vector<uchar>& status)
{
    int j = 0;
    for (int i = 0; i < int(v.size()); i++)
        if (status[i])
            v[j++] = v[i];
    v.resize(j);
}

double FeatureTracker::distance(cv::Point2f &pt1, cv::Point2f &pt2)
{
    double dx = pt1.x - pt2.x;
    double dy = pt1.y - pt2.y;
    return sqrt(dx * dx + dy * dy);
}


FeatureTracker::FeatureTracker()
{
    n_id = 0;
    depthMapFactor = 0.001f;
    mp_gmm = new GMM_Model();
    const char *sidecar = std::getenv("SVIO_XFEAT_XFS");
    if (sidecar != nullptr && sidecar[0] != '\0')
    {
        const char *mode = std::getenv("SVIO_XFEAT_MODE");
        xfeat_hybrid_ = mode != nullptr &&
                        (string(mode) == "hybrid" || string(mode) == "admission");
        xfeat_admission_only_ = mode != nullptr && string(mode) == "admission";
        openXFeatSidecar(sidecar);
    }
}

FeatureTracker::~FeatureTracker()
{
    if (xfeat_enabled_)
        ROS_WARN("XFEAT-SIDECAR frames=%llu mean_emitted=%.2f mean_propagated=%.2f",
                 static_cast<unsigned long long>(xfeat_frames_read_),
                 xfeat_frames_read_ ? static_cast<double>(xfeat_emitted_total_) / xfeat_frames_read_ : 0.0,
                 xfeat_frames_read_ ? static_cast<double>(xfeat_propagated_total_) / xfeat_frames_read_ : 0.0);
    if (mp_gmm)
        delete mp_gmm;
}

namespace
{
template <typename T>
void readExact(std::ifstream &stream, T &value, const char *label)
{
    stream.read(reinterpret_cast<char *>(&value), sizeof(T));
    if (!stream)
        throw std::runtime_error(string("XFeat sidecar truncated at ") + label);
}
}

void FeatureTracker::openXFeatSidecar(const string &path)
{
    xfeat_stream_.open(path.c_str(), std::ios::in | std::ios::binary);
    if (!xfeat_stream_)
        throw std::runtime_error("cannot open XFeat sidecar: " + path);

    char magic[8];
    xfeat_stream_.read(magic, sizeof(magic));
    uint32_t version, width, height, descriptor_dim, proposal_limit, reserved;
    readExact(xfeat_stream_, version, "version");
    readExact(xfeat_stream_, width, "width");
    readExact(xfeat_stream_, height, "height");
    readExact(xfeat_stream_, descriptor_dim, "descriptor_dim");
    readExact(xfeat_stream_, proposal_limit, "proposal_limit");
    readExact(xfeat_stream_, reserved, "reserved");
    readExact(xfeat_stream_, xfeat_frame_count_, "frame_count");
    if (std::memcmp(magic, "XFSIDE01", 8) != 0 || version != 1 ||
        width != 640 || height != 480 || descriptor_dim != 64 ||
        proposal_limit != 500 || reserved != 0 || xfeat_frame_count_ == 0)
        throw std::runtime_error("unsupported XFeat sidecar header: " + path);
    xfeat_enabled_ = true;
    ROS_WARN("XFEAT-SIDECAR enabled path=%s frames=%llu mode=%s",
             path.c_str(), static_cast<unsigned long long>(xfeat_frame_count_),
             xfeat_admission_only_ ? "klt_10hz_admission" :
             (xfeat_hybrid_ ? "klt_10hz_hybrid" : "descriptor_only"));
}

void FeatureTracker::readXFeatRecord(int64_t expected_stamp_ns,
                                      vector<cv::Point2f> &points,
                                      vector<float> &scores,
                                      cv::Mat &descriptors)
{
    int64_t stamp_ns;
    uint32_t count;
    readExact(xfeat_stream_, stamp_ns, "record timestamp");
    readExact(xfeat_stream_, count, "record count");
    if (count > 500)
        throw std::runtime_error("XFeat sidecar record exceeds 500 proposals");
    if (std::llabs(stamp_ns - expected_stamp_ns) > 1000)
        throw std::runtime_error("XFeat/image timestamp mismatch: sidecar=" +
                                 std::to_string(stamp_ns) + " image=" +
                                 std::to_string(expected_stamp_ns));

    vector<float> payload(static_cast<size_t>(count) * 67u);
    xfeat_stream_.read(reinterpret_cast<char *>(payload.data()),
                       static_cast<std::streamsize>(payload.size() * sizeof(float)));
    if (!xfeat_stream_)
        throw std::runtime_error("XFeat sidecar truncated in feature payload");

    points.resize(count);
    scores.resize(count);
    descriptors.create(static_cast<int>(count), 64, CV_32F);
    for (uint32_t i = 0; i < count; ++i)
    {
        const float *src = payload.data() + static_cast<size_t>(i) * 67u;
        points[i] = cv::Point2f(src[0], src[1]);
        scores[i] = src[2];
        float *dst = descriptors.ptr<float>(static_cast<int>(i));
        std::memcpy(dst, src + 3, 64 * sizeof(float));
        const float norm = std::sqrt(std::max(1e-20f, static_cast<float>(cv::norm(descriptors.row(static_cast<int>(i)), cv::NORM_L2SQR))));
        for (int d = 0; d < 64; ++d)
            dst[d] /= norm;
    }
    ++xfeat_frames_read_;
}

void FeatureTracker::readIntrinsicParameter(const string &calib_file)
{
    camera = CameraFactory::instance()->generateCameraFromYamlFile(calib_file);
    row = camera->imageHeight();
    col = camera->imageWidth();
}


void FeatureTracker::setMask()
{
    mask = cv::Mat(row, col, CV_8UC1, cv::Scalar(255));

    // prefer to keep features that are tracked for long time
    vector<pair<int, pair<cv::Point2f, int>>> cnt_pts_id;

    for (unsigned int i = 0; i < cur_pts.size(); i++)
        cnt_pts_id.push_back(make_pair(track_cnt[i], make_pair(cur_pts[i], ids[i])));

    sort(cnt_pts_id.begin(), cnt_pts_id.end(), [](const pair<int, pair<cv::Point2f, int>> &a, const pair<int, pair<cv::Point2f, int>> &b)
         {
            return a.first > b.first;
         });

    cur_pts.clear();
    ids.clear();
    track_cnt.clear();

    for (auto &it : cnt_pts_id)
    {
        if (mask.at<uchar>(it.second.first) == 255)
        {
            cur_pts.push_back(it.second.first);
            ids.push_back(it.second.second);
            track_cnt.push_back(it.first);
            cv::circle(mask, it.second.first, MIN_DIST, 0, -1);
        }
    }
}

void FeatureTracker::addPoints()
{
    for (auto &p : n_pts)
    {
        cur_pts.push_back(p);
        ids.push_back(n_id++);
        track_cnt.push_back(1);
    }
}

void FeatureTracker::rejectWithF()
{
    if (prev_pts.size() >= 8)
    {
        vector<cv::Point2f> un_prev_pts(prev_pts.size()), un_cur_pts(cur_pts.size());
        for (unsigned int i = 0; i < prev_pts.size(); i++)
        {
            Eigen::Vector3d tmp_p;
            camera->liftProjective(Eigen::Vector2d(prev_pts[i].x, prev_pts[i].y), tmp_p);
            tmp_p.x() = FOCAL_LENGTH * tmp_p.x() / tmp_p.z() + col / 2.0;
            tmp_p.y() = FOCAL_LENGTH * tmp_p.y() / tmp_p.z() + row / 2.0;
            un_prev_pts[i] = cv::Point2f(tmp_p.x(), tmp_p.y());

           camera->liftProjective(Eigen::Vector2d(cur_pts[i].x, cur_pts[i].y), tmp_p);
            tmp_p.x() = FOCAL_LENGTH * tmp_p.x() / tmp_p.z() + col / 2.0;
            tmp_p.y() = FOCAL_LENGTH * tmp_p.y() / tmp_p.z() + row / 2.0;
            un_cur_pts[i] = cv::Point2f(tmp_p.x(), tmp_p.y());
        }

        vector<uchar> status;
        cv::findFundamentalMat(un_prev_pts, un_cur_pts, cv::FM_RANSAC, F_THRESHOLD, 0.99, status);
        int size_a = prev_pts.size();
        reduceVector(prev_pts, status);
        reduceVector(cur_pts, status);
        reduceVector(ids, status);
        reduceVector(track_cnt, status);
        ROS_DEBUG("FM ransac: %d -> %lu: %f", size_a, cur_pts.size(), 1.0 * cur_pts.size() / size_a);
    }
}

void FeatureTracker::undistortedPoints()
{
    cur_un_pts.clear();
    cur_un_pts_map.clear();
    //cv::undistortPoints(cur_pts, un_pts, K, cv::Mat());
    for (unsigned int i = 0; i < cur_pts.size(); i++)
    {
        Eigen::Vector2d a(cur_pts[i].x, cur_pts[i].y);
        Eigen::Vector3d b;
        camera->liftProjective(a, b);
        cur_un_pts.push_back(cv::Point2f(b.x() / b.z(), b.y() / b.z()));
        cur_un_pts_map.insert(make_pair(ids[i], cv::Point2f(b.x() / b.z(), b.y() / b.z())));
    }

    // caculate points velocity
    if (!prev_un_pts_map.empty())
    {
        double dt = cur_time - prev_time;
        pts_velocity.clear();
        for (unsigned int i = 0; i < cur_un_pts.size(); i++)
        {
            if (ids[i] != -1)
            {
                std::map<int, cv::Point2f>::iterator it;
                it = prev_un_pts_map.find(ids[i]);
                if (it != prev_un_pts_map.end())
                {
                    double v_x = (cur_un_pts[i].x - it->second.x) / dt;
                    double v_y = (cur_un_pts[i].y - it->second.y) / dt;
                    pts_velocity.push_back(cv::Point2f(v_x, v_y));
                }
                else
                    pts_velocity.push_back(cv::Point2f(0, 0));
            }
            else
            {
                pts_velocity.push_back(cv::Point2f(0, 0));
            }
        }
    }
    else
    {
        for (unsigned int i = 0; i < cur_pts.size(); i++)
        {
            pts_velocity.push_back(cv::Point2f(0, 0));
        }
    }
    prev_un_pts_map.swap(cur_un_pts_map);
}


void FeatureTracker::trackImage(const cv::Mat &mono_img, double _cur_time)
{
    if (xfeat_enabled_)
    {
        if (xfeat_hybrid_)
            trackImageHybrid(mono_img, _cur_time);
        else
            trackImageXFeat(mono_img, _cur_time);
        return;
    }

    prev_img = cur_img;
    prev_pts.swap(cur_pts);
    prev_un_pts.swap(cur_un_pts);
    prev_time = cur_time;

    cur_img = mono_img;
    cur_time = _cur_time;
    cur_pts.clear();

    if (prev_pts.size() > 0)
    {
        TicToc t_o;
        vector<uchar> status;
        vector<float> err;
        cv::calcOpticalFlowPyrLK(prev_img, cur_img, prev_pts, cur_pts, status, err, cv::Size(21, 21), 3);

        if (FLOW_BACK != 0)
        {
            vector<cv::Point2f> reverse_pts = prev_pts;
            vector<uchar> reverse_status;
            vector<float> reverse_err;
            cv::calcOpticalFlowPyrLK(cur_img, prev_img, cur_pts, reverse_pts, reverse_status, reverse_err, cv::Size(21, 21), 3);
            PHASE2_COUNTERS.flow_back_checks.fetch_add(status.size(), std::memory_order_relaxed);
            for (int i = 0; i < int(status.size()); i++)
            {
                status[i] = status[i] && reverse_status[i] && distance(prev_pts[i], reverse_pts[i]) <= 0.5;
            }
        }

        for (int i = 0; i < int(cur_pts.size()); i++)
            if (status[i] && !inBorder(cur_pts[i]))
                status[i] = 0;
        reduceVector(prev_pts, status);
        reduceVector(cur_pts, status);
        reduceVector(ids, status);
        reduceVector(track_cnt, status);
    }

    for (auto &n : track_cnt)
        n++;

    rejectWithF();

    setMask();

    int n_max_cnt = MAX_CNT - static_cast<int>(cur_pts.size());
    if (n_max_cnt > 0)
        cv::goodFeaturesToTrack(cur_img, n_pts, MAX_CNT - cur_pts.size(), 0.01, MIN_DIST, mask);
    else
        n_pts.clear();

    addPoints();

    undistortedPoints();
}

void FeatureTracker::trackImageXFeat(const cv::Mat &mono_img, double _cur_time)
{
    prev_img = cur_img;
    prev_pts = cur_pts;
    prev_un_pts.swap(cur_un_pts);
    prev_time = cur_time;
    cur_img = mono_img;
    cur_time = _cur_time;
    cur_pts.clear();
    ids.clear();
    track_cnt.clear();

    vector<cv::Point2f> proposal_pts;
    vector<float> proposal_scores;
    cv::Mat proposal_desc;
    readXFeatRecord(static_cast<int64_t>(std::llround(_cur_time * 1e9)),
                    proposal_pts, proposal_scores, proposal_desc);

    struct MatchCandidate
    {
        int prev_index;
        int cur_index;
        int id;
        int age;
        float cosine;
    };
    vector<MatchCandidate> propagated;

    if (!xfeat_prev_desc_.empty() && !proposal_desc.empty())
    {
        cv::Mat similarity = xfeat_prev_desc_ * proposal_desc.t();
        vector<int> prev_best(xfeat_prev_desc_.rows, -1);
        vector<int> cur_best(proposal_desc.rows, -1);
        vector<float> prev_best_value(xfeat_prev_desc_.rows,
                                      -std::numeric_limits<float>::infinity());
        vector<float> cur_best_value(proposal_desc.rows,
                                     -std::numeric_limits<float>::infinity());
        for (int p = 0; p < similarity.rows; ++p)
        {
            const float *row_ptr = similarity.ptr<float>(p);
            for (int q = 0; q < similarity.cols; ++q)
            {
                const float value = row_ptr[q];
                if (value > prev_best_value[p])
                {
                    prev_best_value[p] = value;
                    prev_best[p] = q;
                }
                if (value > cur_best_value[q])
                {
                    cur_best_value[q] = value;
                    cur_best[q] = p;
                }
            }
        }

        for (int p = 0; p < static_cast<int>(prev_best.size()); ++p)
        {
            const int q = prev_best[p];
            if (q >= 0 && cur_best[q] == p && prev_best_value[p] > 0.82f &&
                inBorder(proposal_pts[q]))
            {
                propagated.push_back({p, q, xfeat_prev_proposal_ids_[p],
                                      xfeat_prev_proposal_age_[p] + 1,
                                      prev_best_value[p]});
            }
        }

        // Match identity is supplied by XFeat.  The same geometry-only
        // rejection used by the original front end removes gross identities
        // before they reach the unchanged local BA.
        if (propagated.size() >= 8)
        {
            vector<cv::Point2f> un_prev(propagated.size());
            vector<cv::Point2f> un_cur(propagated.size());
            for (size_t i = 0; i < propagated.size(); ++i)
            {
                Eigen::Vector3d ray;
                const cv::Point2f &old_pt = xfeat_prev_proposal_pts_[propagated[i].prev_index];
                const cv::Point2f &new_pt = proposal_pts[propagated[i].cur_index];
                camera->liftProjective(Eigen::Vector2d(old_pt.x, old_pt.y), ray);
                un_prev[i] = cv::Point2f(FOCAL_LENGTH * ray.x() / ray.z() + col / 2.0,
                                         FOCAL_LENGTH * ray.y() / ray.z() + row / 2.0);
                camera->liftProjective(Eigen::Vector2d(new_pt.x, new_pt.y), ray);
                un_cur[i] = cv::Point2f(FOCAL_LENGTH * ray.x() / ray.z() + col / 2.0,
                                        FOCAL_LENGTH * ray.y() / ray.z() + row / 2.0);
            }
            vector<uchar> status;
            cv::findFundamentalMat(un_prev, un_cur, cv::FM_RANSAC,
                                   F_THRESHOLD, 0.99, status);
            if (status.size() == propagated.size())
            {
                size_t out = 0;
                for (size_t i = 0; i < propagated.size(); ++i)
                    if (status[i])
                        propagated[out++] = propagated[i];
                propagated.resize(out);
            }
        }
    }

    std::sort(propagated.begin(), propagated.end(),
              [](const MatchCandidate &a, const MatchCandidate &b)
              {
                  if (a.age != b.age)
                      return a.age > b.age;
                  if (a.cosine != b.cosine)
                      return a.cosine > b.cosine;
                  return a.id < b.id;
              });

    mask = cv::Mat(row, col, CV_8UC1, cv::Scalar(255));
    vector<int> selected_proposal_indices;
    selected_proposal_indices.reserve(MAX_CNT);
    vector<uchar> proposal_used(proposal_pts.size(), 0);
    int propagated_emitted = 0;
    for (const MatchCandidate &candidate : propagated)
    {
        if (static_cast<int>(cur_pts.size()) >= MAX_CNT)
            break;
        const cv::Point2f &point = proposal_pts[candidate.cur_index];
        const int x = cvRound(point.x);
        const int y = cvRound(point.y);
        if (!inBorder(point) || mask.at<uchar>(y, x) == 0)
            continue;
        cur_pts.push_back(point);
        ids.push_back(candidate.id);
        track_cnt.push_back(candidate.age);
        selected_proposal_indices.push_back(candidate.cur_index);
        proposal_used[candidate.cur_index] = 1;
        cv::circle(mask, point, MIN_DIST, 0, -1);
        ++propagated_emitted;
    }

    vector<int> score_order(proposal_pts.size());
    for (int i = 0; i < static_cast<int>(score_order.size()); ++i)
        score_order[i] = i;
    std::stable_sort(score_order.begin(), score_order.end(),
                     [&proposal_scores](int a, int b)
                     {
                         return proposal_scores[a] > proposal_scores[b];
                     });
    for (int q : score_order)
    {
        if (static_cast<int>(cur_pts.size()) >= MAX_CNT)
            break;
        const cv::Point2f &point = proposal_pts[q];
        const int x = cvRound(point.x);
        const int y = cvRound(point.y);
        if (proposal_used[q] || !inBorder(point) || mask.at<uchar>(y, x) == 0)
            continue;
        cur_pts.push_back(point);
        ids.push_back(n_id++);
        track_cnt.push_back(1);
        selected_proposal_indices.push_back(q);
        proposal_used[q] = 1;
        cv::circle(mask, point, MIN_DIST, 0, -1);
    }

    xfeat_prev_desc_.create(static_cast<int>(selected_proposal_indices.size()), 64, CV_32F);
    for (int i = 0; i < static_cast<int>(selected_proposal_indices.size()); ++i)
        proposal_desc.row(selected_proposal_indices[i]).copyTo(xfeat_prev_desc_.row(i));
    xfeat_prev_proposal_pts_ = cur_pts;
    xfeat_prev_proposal_ids_ = ids;
    xfeat_prev_proposal_age_ = track_cnt;
    xfeat_propagated_total_ += static_cast<uint64_t>(propagated_emitted);
    xfeat_emitted_total_ += static_cast<uint64_t>(cur_pts.size());

    if (xfeat_frames_read_ == 1 || xfeat_frames_read_ % 100 == 0)
        ROS_WARN("XFEAT-SIDECAR frame=%llu emitted=%zu propagated=%d",
                 static_cast<unsigned long long>(xfeat_frames_read_),
                 cur_pts.size(), propagated_emitted);

    undistortedPoints();
}

void FeatureTracker::trackImageHybrid(const cv::Mat &mono_img, double _cur_time)
{
    prev_img = cur_img;
    prev_pts.swap(cur_pts);
    prev_un_pts.swap(cur_un_pts);
    prev_time = cur_time;
    cur_img = mono_img;
    cur_time = _cur_time;
    cur_pts.clear();

    vector<cv::Point2f> proposal_pts;
    vector<float> proposal_scores;
    cv::Mat proposal_desc;
    readXFeatRecord(static_cast<int64_t>(std::llround(_cur_time * 1e9)),
                    proposal_pts, proposal_scores, proposal_desc);
    const bool xfeat_tick = ((xfeat_frames_read_ - 1u) % 3u) == 0u;

    auto reduceHybrid = [this](const vector<uchar> &status)
    {
        int out = 0;
        for (int i = 0; i < static_cast<int>(status.size()); ++i)
        {
            if (!status[i])
                continue;
            hybrid_anchor_desc_[out] = hybrid_anchor_desc_[i];
            hybrid_has_anchor_[out] = hybrid_has_anchor_[i];
            ++out;
        }
        hybrid_anchor_desc_.resize(out);
        hybrid_has_anchor_.resize(out);
    };

    if (!prev_pts.empty())
    {
        vector<uchar> status;
        vector<float> err;
        cv::calcOpticalFlowPyrLK(prev_img, cur_img, prev_pts, cur_pts,
                                 status, err, cv::Size(21, 21), 3);
        if (FLOW_BACK != 0)
        {
            vector<cv::Point2f> reverse_pts = prev_pts;
            vector<uchar> reverse_status;
            vector<float> reverse_err;
            cv::calcOpticalFlowPyrLK(cur_img, prev_img, cur_pts, reverse_pts,
                                     reverse_status, reverse_err,
                                     cv::Size(21, 21), 3);
            PHASE2_COUNTERS.flow_back_checks.fetch_add(status.size(), std::memory_order_relaxed);
            for (int i = 0; i < static_cast<int>(status.size()); ++i)
                status[i] = status[i] && reverse_status[i] &&
                            distance(prev_pts[i], reverse_pts[i]) <= 0.5;
        }
        for (int i = 0; i < static_cast<int>(cur_pts.size()); ++i)
            if (status[i] && !inBorder(cur_pts[i]))
                status[i] = 0;
        reduceHybrid(status);
        reduceVector(prev_pts, status);
        reduceVector(cur_pts, status);
        reduceVector(ids, status);
        reduceVector(track_cnt, status);
    }

    for (int &age : track_cnt)
        ++age;

    // Preserve the frozen KLT front end's two-view geometric rejection.
    bool xfeat_health_valid = false;
    size_t xfeat_post_f_survivors = cur_pts.size();
    if (prev_pts.size() >= 8)
    {
        vector<cv::Point2f> un_prev(prev_pts.size()), un_cur(cur_pts.size());
        for (size_t i = 0; i < prev_pts.size(); ++i)
        {
            Eigen::Vector3d ray;
            camera->liftProjective(Eigen::Vector2d(prev_pts[i].x, prev_pts[i].y), ray);
            un_prev[i] = cv::Point2f(FOCAL_LENGTH * ray.x() / ray.z() + col / 2.0,
                                     FOCAL_LENGTH * ray.y() / ray.z() + row / 2.0);
            camera->liftProjective(Eigen::Vector2d(cur_pts[i].x, cur_pts[i].y), ray);
            un_cur[i] = cv::Point2f(FOCAL_LENGTH * ray.x() / ray.z() + col / 2.0,
                                    FOCAL_LENGTH * ray.y() / ray.z() + row / 2.0);
        }
        vector<uchar> status;
        cv::findFundamentalMat(un_prev, un_cur, cv::FM_RANSAC,
                               F_THRESHOLD, 0.99, status);
        if (status.size() == cur_pts.size())
        {
            reduceHybrid(status);
            reduceVector(prev_pts, status);
            reduceVector(cur_pts, status);
            reduceVector(ids, status);
            reduceVector(track_cnt, status);
            xfeat_health_valid = true;
            xfeat_post_f_survivors = cur_pts.size();
        }
    }

    // A two-frame post-F shortage is the only learned-admission selector.
    // Four fifths of MAX_CNT is 120 under the frozen 150-track budget.
    if (xfeat_admission_only_)
    {
        const size_t threshold = static_cast<size_t>((4 * MAX_CNT) / 5);
        if (xfeat_health_valid && xfeat_post_f_survivors < threshold)
            xfeat_low_health_streak_ = std::min<uint32_t>(2u, xfeat_low_health_streak_ + 1u);
        else
            xfeat_low_health_streak_ = 0u;
    }
    const bool xfeat_health_ready = !xfeat_admission_only_ ||
                                    xfeat_low_health_streak_ >= 2u;

    vector<uchar> proposal_used(proposal_pts.size(), 0);
    int xfeat_validated = 0;
    if (!xfeat_admission_only_ && xfeat_tick && !cur_pts.empty() && !proposal_desc.empty())
    {
        vector<int> anchored_tracks;
        for (int i = 0; i < static_cast<int>(cur_pts.size()); ++i)
            if (hybrid_has_anchor_[i])
                anchored_tracks.push_back(i);

        vector<int> assigned(cur_pts.size(), -1);
        vector<uchar> keep(cur_pts.size(), 1);
        if (!anchored_tracks.empty())
        {
            cv::Mat anchors(static_cast<int>(anchored_tracks.size()), 64, CV_32F);
            for (int r = 0; r < static_cast<int>(anchored_tracks.size()); ++r)
                std::memcpy(anchors.ptr<float>(r),
                            hybrid_anchor_desc_[anchored_tracks[r]].data(),
                            64 * sizeof(float));
            cv::Mat similarity = anchors * proposal_desc.t();
            vector<int> anchor_best(anchors.rows, -1);
            vector<int> proposal_best(proposal_desc.rows, -1);
            vector<float> anchor_value(anchors.rows, -std::numeric_limits<float>::infinity());
            vector<float> proposal_value(proposal_desc.rows, -std::numeric_limits<float>::infinity());
            for (int a = 0; a < similarity.rows; ++a)
            {
                const float *row_ptr = similarity.ptr<float>(a);
                for (int q = 0; q < similarity.cols; ++q)
                {
                    const float value = row_ptr[q];
                    if (value > anchor_value[a])
                    {
                        anchor_value[a] = value;
                        anchor_best[a] = q;
                    }
                    if (value > proposal_value[q])
                    {
                        proposal_value[q] = value;
                        proposal_best[q] = a;
                    }
                }
            }
            for (int a = 0; a < static_cast<int>(anchored_tracks.size()); ++a)
            {
                const int track_index = anchored_tracks[a];
                const int q = anchor_best[a];
                const bool descriptor_ok = q >= 0 && proposal_best[q] == a &&
                                           anchor_value[a] > 0.82f;
                const bool endpoint_ok = descriptor_ok &&
                    cv::norm(cur_pts[track_index] - proposal_pts[q]) <= F_THRESHOLD;
                if (!endpoint_ok)
                {
                    keep[track_index] = 0;
                    continue;
                }
                assigned[track_index] = q;
                proposal_used[q] = 1;
                std::memcpy(hybrid_anchor_desc_[track_index].data(),
                            proposal_desc.ptr<float>(q), 64 * sizeof(float));
                ++xfeat_validated;
            }
        }

        // First-time association is not a revival: it only attaches a
        // descriptor anchor to a KLT identity observed in this same frame.
        for (int i = 0; i < static_cast<int>(cur_pts.size()); ++i)
        {
            if (!keep[i] || hybrid_has_anchor_[i])
                continue;
            int best_q = -1;
            float best_d2 = static_cast<float>(F_THRESHOLD * F_THRESHOLD);
            for (int q = 0; q < static_cast<int>(proposal_pts.size()); ++q)
            {
                if (proposal_used[q])
                    continue;
                const cv::Point2f delta = cur_pts[i] - proposal_pts[q];
                const float d2 = delta.dot(delta);
                if (d2 <= best_d2)
                {
                    best_d2 = d2;
                    best_q = q;
                }
            }
            if (best_q >= 0)
            {
                assigned[i] = best_q;
                proposal_used[best_q] = 1;
                hybrid_has_anchor_[i] = 1;
                std::memcpy(hybrid_anchor_desc_[i].data(),
                            proposal_desc.ptr<float>(best_q), 64 * sizeof(float));
            }
        }

        reduceHybrid(keep);
        reduceVector(prev_pts, keep);
        reduceVector(cur_pts, keep);
        reduceVector(ids, keep);
        reduceVector(track_cnt, keep);
    }

    // Original age-prioritized spatial budget, with descriptor state carried
    // alongside each KLT identity.
    vector<int> order(cur_pts.size());
    for (int i = 0; i < static_cast<int>(order.size()); ++i)
        order[i] = i;
    std::stable_sort(order.begin(), order.end(),
                     [this](int a, int b)
                     {
                         return track_cnt[a] > track_cnt[b];
                     });
    mask = cv::Mat(row, col, CV_8UC1, cv::Scalar(255));
    vector<cv::Point2f> kept_pts;
    vector<int> kept_ids, kept_age;
    vector<array<float, 64>> kept_desc;
    vector<uchar> kept_has;
    for (int index : order)
    {
        const cv::Point2f &point = cur_pts[index];
        const int x = cvRound(point.x), y = cvRound(point.y);
        if (!inBorder(point) || mask.at<uchar>(y, x) == 0)
            continue;
        kept_pts.push_back(point);
        kept_ids.push_back(ids[index]);
        kept_age.push_back(track_cnt[index]);
        kept_desc.push_back(hybrid_anchor_desc_[index]);
        kept_has.push_back(hybrid_has_anchor_[index]);
        cv::circle(mask, point, MIN_DIST, 0, -1);
    }
    cur_pts.swap(kept_pts);
    ids.swap(kept_ids);
    track_cnt.swap(kept_age);
    hybrid_anchor_desc_.swap(kept_desc);
    hybrid_has_anchor_.swap(kept_has);

    const bool xfeat_admit = xfeat_tick && xfeat_health_ready;

    if (xfeat_admit)
    {
        vector<int> score_order(proposal_pts.size());
        for (int i = 0; i < static_cast<int>(score_order.size()); ++i)
            score_order[i] = i;
        std::stable_sort(score_order.begin(), score_order.end(),
                         [&proposal_scores](int a, int b)
                         {
                             return proposal_scores[a] > proposal_scores[b];
                         });
        for (int q : score_order)
        {
            if (static_cast<int>(cur_pts.size()) >= MAX_CNT)
                break;
            const cv::Point2f &point = proposal_pts[q];
            const int x = cvRound(point.x), y = cvRound(point.y);
            if (proposal_used[q] || !inBorder(point) || mask.at<uchar>(y, x) == 0)
                continue;
            cur_pts.push_back(point);
            ids.push_back(n_id++);
            track_cnt.push_back(1);
            array<float, 64> descriptor = {};
            if (!xfeat_admission_only_)
                std::memcpy(descriptor.data(), proposal_desc.ptr<float>(q), 64 * sizeof(float));
            hybrid_anchor_desc_.push_back(descriptor);
            hybrid_has_anchor_.push_back(xfeat_admission_only_ ? 0 : 1);
            proposal_used[q] = 1;
            cv::circle(mask, point, MIN_DIST, 0, -1);
        }
    }

    const int remaining = MAX_CNT - static_cast<int>(cur_pts.size());
    if (remaining > 0)
        cv::goodFeaturesToTrack(cur_img, n_pts, remaining, 0.01, MIN_DIST, mask);
    else
        n_pts.clear();
    for (const cv::Point2f &point : n_pts)
    {
        cur_pts.push_back(point);
        ids.push_back(n_id++);
        track_cnt.push_back(1);
        hybrid_anchor_desc_.push_back(array<float, 64>());
        hybrid_has_anchor_.push_back(0);
    }

    xfeat_propagated_total_ += static_cast<uint64_t>(xfeat_validated);
    xfeat_emitted_total_ += static_cast<uint64_t>(cur_pts.size());
    if (xfeat_frames_read_ == 1 || xfeat_frames_read_ % 100 == 0)
        ROS_WARN("XFEAT-HYBRID frame=%llu mode=%s tick=%d admit=%d survivors=%zu emitted=%zu validated=%d anchored=%zu",
                 static_cast<unsigned long long>(xfeat_frames_read_),
                 xfeat_admission_only_ ? "admission" : "validate",
                 xfeat_tick ? 1 : 0, xfeat_admit ? 1 : 0, xfeat_post_f_survivors,
                 cur_pts.size(), xfeat_validated,
                 static_cast<size_t>(std::count(hybrid_has_anchor_.begin(),
                                                hybrid_has_anchor_.end(), 1)));

    undistortedPoints();
}

void FeatureTracker::associateDepthGMM(const cv::Mat &dpt, bool use_sim)
{
    cur_pts_depth.resize(cur_pts.size());
    for (int i = 0; i < cur_pts.size(); i++)
    {
        float ui = cur_pts[i].x, vi = cur_pts[i].y;
        float d = (float)dpt.at<unsigned short>(std::round(vi), std::round(ui)) * depthMapFactor;
        if (d >= RGBD_DPT_MIN && d <= RGBD_DPT_MAX)
        {
            double mu_d, mu_l, sig_d, sig_l;
            mp_gmm->gmm_model_depth(std::round(vi), std::round(ui), dpt, mu_d, sig_d, use_sim ? 1 : 0);
            mp_gmm->gmm_model_inv_depth(std::round(vi), std::round(ui), dpt, mu_l, sig_l, use_sim ? 1 : 0);
            cur_pts_depth[i] = cv::Vec4f(mu_d, mu_l, sig_d, sig_l); 
        }   
        else
            cur_pts_depth[i] = cv::Vec4f(-1,-1,-1,-1);
    }
}

void FeatureTracker::associateDepthSimple(const cv::Mat &dpt)
{
    cur_pts_depth.clear();
    cur_pts_depth.reserve(cur_pts.size());
    static poly cp_depth_cov;
    for (int i = 0; i < cur_pts.size(); i++)
    {
        float ui = cur_pts[i].x, vi = cur_pts[i].y;
        float d = (float)dpt.at<unsigned short>(std::round(vi), std::round(ui)) * depthMapFactor;
        if (d >= RGBD_DPT_MIN && d <= RGBD_DPT_MAX)
            cur_pts_depth.push_back(cv::Vec4f(d, 1./d, cp_depth_cov.y(d), 0.0005));
        else
            cur_pts_depth.push_back(cv::Vec4f(0,0,0));
    }
}

void FeatureTracker::associatePlane(const PlaneDetection& plane_detector)
{
    cur_pts_plane_index.clear();
    cur_pts_plane_index.reserve(cur_pts.size());
    for (int i = 0; i < cur_pts.size(); i++)
    {
        int ui = round(cur_pts[i].x/2), vi = round(cur_pts[i].y/2);
        cv::Vec3b color = plane_detector.seg_img_.at<cv::Vec3b>(vi,ui); 
        if (color == cv::Vec3b::zeros())
            cur_pts_plane_index.push_back(-1);
        else
        {
            int key_c = color(0)+256*color(1)+256*256*color(2);
            auto it = plane_detector.c_book.find(key_c);
            cur_pts_plane_index.push_back(it->second);
        }
    }
}

void FeatureTracker::removeOutliers(set<int> &removePtsIds)
{
    std::set<int>::iterator itSet;
    vector<uchar> status;
    for (size_t i = 0; i < ids.size(); i++)
    {
        itSet = removePtsIds.find(ids[i]);
        if(itSet != removePtsIds.end())
            status.push_back(0);
        else
            status.push_back(1);
    }

    reduceVector(prev_pts, status);
    reduceVector(ids, status);
    reduceVector(track_cnt, status);
}

cv::Mat FeatureTracker::drawImTrack(const cv::Mat& color_img)
{
    cv::Mat imTrack = color_img.clone();
    const int LEN_TH = 5;
    for (int i = 0; i < cur_pts.size(); i++)
    {
        double len = std::min(1.0, 1.0 * track_cnt[i] / LEN_TH);
        cv::circle(imTrack, cur_pts[i], 2, cv::Scalar(255 * (1 - len), 0, 255 * len), 2);
    }
    return imTrack;
}
