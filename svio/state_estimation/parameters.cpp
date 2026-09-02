#include "parameters.h"
#include <cmath>
#include <cstdlib>

// Paras for identifying structural elements
double STRUCTURE_HORIZONTAL_ANG_DIFF;
double LINE_STRUCTURE_HORIZONTAL_ANG_DIFF;
double STRUCTURE_VERTICAL_ANG_DIFF;

// Paras for identifying outliers
double ERR_PT_LINE_REPRO; 
double ERR_N_LINE_REPRO; 
double ERR_POINT_REPRO;
double ERR_PLANE_DIST;

// Paras for result format
bool SAVE_TUM;

double INIT_DEPTH;
double MIN_PARALLAX;
double ACC_N, ACC_W;
double GYR_N, GYR_W;

std::vector<Eigen::Matrix3d> RIC;
std::vector<Eigen::Vector3d> TIC;

Eigen::Vector3d G{0.0, 0.0, 9.8};

double BIAS_ACC_THRESHOLD;
double BIAS_GYR_THRESHOLD;
double SOLVER_TIME;
int NUM_ITERATIONS;
int MIN_USED_NUM = 4;
int ESTIMATE_EXTRINSIC;
std::string EX_CALIB_RESULT_PATH;
std::string VINS_RESULT_PATH;
std::string VINS_STATS_PATH;
int LOOP_CLOSURE = 0;
int MIN_LOOP_NUM;
std::string CAM_NAMES;
// std::vector<std::string> CAM_NAMES;
std::string PATTERN_FILE;
std::string VOC_FILE;
int IMAGE_ROW, IMAGE_COL;
std::string VINS_FOLDER_PATH;
int MAX_KEYFRAME_NUM;
double PIX_SIGMA, FX, FY, CX, CY; 

int MAX_CNT;
int MIN_DIST;
double F_THRESHOLD;
int SHOW_TRACK;
int FLOW_BACK = 0;
bool PUB_THIS_FRAME = true;

double RGBD_DPT_MIN, RGBD_DPT_MAX;
int S_VERIFY = 1; // whether use two-stage aw interference
int ENABLE_STRUCTURE = 1;

int DROP_FRAME = 0;
int FREQ = 0;
bool ENABLE_FREQ_GATE = false;

double ACC_MULT; 

bool USE_GMM = true; // whether use gmm to compute covariance 
bool USE_GMM_EXT = true; // whether extend gmm by introducing similarity 
bool ENABLE_PLANE = true;
bool ENABLE_LINE = false;
Phase2RuntimeCounters PHASE2_COUNTERS;

namespace
{
bool first_frequency_frame = true;
double first_frequency_time = 0.0;
double last_frequency_time = 0.0;
int frequency_publish_count = 1;

int optionalInt(const cv::FileStorage& settings, const char* key, int fallback)
{
    const cv::FileNode node = settings[key];
    if (node.empty())
        return fallback;
    int value = fallback;
    node >> value;
    return value;
}

bool optionalBool(const cv::FileStorage& settings, const char* key, bool fallback)
{
    return optionalInt(settings, key, fallback ? 1 : 0) != 0;
}
}


template <typename T>
T readParam(ros::NodeHandle &n, std::string name)
{
    T ans;
    if (n.getParam(name, ans))
    {
        ROS_INFO_STREAM("Loaded " << name << ": " << ans);
    }
    else
    {
        ROS_ERROR_STREAM("Failed to load " << name);
        n.shutdown();
    }
    return ans;
}

void readParameters(ros::NodeHandle &n)
{
    static bool once = false; 
    if(once ) return; 
    std::string config_file("/home/davidz/work/ros/kinetic/src/demo_rgbd_new/config/downsample.yaml");
    // config_file = readParam<std::string>(n, "config_file");
    n.param("config_file", config_file, config_file); 
    cv::FileStorage fsSettings(config_file, cv::FileStorage::READ);
    if(!fsSettings.isOpened())
    {
        std::cerr << "ERROR: Wrong path to settings, config_file = " << config_file << std::endl;
    }
    else
    {
        ROS_DEBUG("parameters.cpp: succeed to load config_file: %s", config_file.c_str());
    }

    ACC_MULT = fsSettings["acc_mult"];
    MAX_CNT = fsSettings["max_cnt"];
    MIN_DIST = fsSettings["min_dist"];
    F_THRESHOLD = fsSettings["F_threshold"];
    SHOW_TRACK = fsSettings["show_track"];
    FREQ = optionalInt(fsSettings, "freq", FREQ);
    ENABLE_FREQ_GATE = optionalBool(fsSettings, "freq_gate", ENABLE_FREQ_GATE);
    FLOW_BACK = optionalInt(fsSettings, "flow_back", FLOW_BACK);
    DROP_FRAME = optionalInt(fsSettings, "drop_frame", DROP_FRAME);

    IMAGE_COL = fsSettings["image_width"];
    IMAGE_ROW = fsSettings["image_height"];

    SOLVER_TIME = fsSettings["max_solver_time"];
    NUM_ITERATIONS = fsSettings["max_num_iterations"];
    MIN_PARALLAX = fsSettings["keyframe_parallax"];
    MIN_PARALLAX = MIN_PARALLAX / FOCAL_LENGTH;

    fsSettings["output_path"] >> VINS_RESULT_PATH;
    VINS_STATS_PATH = VINS_RESULT_PATH + "/stats.csv"; 
    std::ofstream foutA(VINS_STATS_PATH, std::ios::out);
    foutA.close();
    VINS_RESULT_PATH = VINS_RESULT_PATH + "/svio_no_loop.csv"; 
    std::ofstream foutC(VINS_RESULT_PATH, std::ios::out);
    foutC.close();
    ROS_INFO("output path: %s", VINS_RESULT_PATH.c_str());

    ACC_N = fsSettings["acc_n"];
    ACC_W = fsSettings["acc_w"];
    GYR_N = fsSettings["gyr_n"];
    GYR_W = fsSettings["gyr_w"];
    G.z() = fsSettings["g_norm"];

    // Paras for identifying structural elements
    STRUCTURE_HORIZONTAL_ANG_DIFF = fsSettings["horizontal_structural_th"];
    LINE_STRUCTURE_HORIZONTAL_ANG_DIFF = fsSettings["line_horizontal_structural_th"];
    STRUCTURE_VERTICAL_ANG_DIFF = fsSettings["vertical_structural_th"];

    // Paras for identifying outliers
    ERR_PT_LINE_REPRO = fsSettings["err_pt_line"]; 
    ERR_N_LINE_REPRO = fsSettings["err_normal_line"]; 
    ERR_POINT_REPRO = fsSettings["err_point"];
    ERR_PLANE_DIST = fsSettings["err_plane_dist"];

    // Paras for result format
    int read_int = fsSettings["save_tum"];
    SAVE_TUM = (read_int==0)?false:true;

    // Paras for used line/point number
    MIN_USED_NUM = fsSettings["min_used_num"];

    PIX_SIGMA = fsSettings["F_threshold"];
    ROS_DEBUG("SOLVER_TIME: %lf PIX_SIGMA = %lf ACC_N = %lf ACC_W = %lf GYR_N = %lf GYR_W = %lf G.z = %lf", SOLVER_TIME, PIX_SIGMA, ACC_N, ACC_W, GYR_N, GYR_W, G.z());

    cv::FileNode node = fsSettings["projection_parameters"];
    FX = static_cast<double>(node["fx"]);
    FY = static_cast<double>(node["fy"]);
    CX = static_cast<double>(node["cx"]);
    CY = static_cast<double>(node["cy"]);
    ROS_DEBUG("FX = %f FY = %f CX = %f CY = %f", FX, FY, CX, CY);

    ESTIMATE_EXTRINSIC = fsSettings["estimate_extrinsic"];
    if (ESTIMATE_EXTRINSIC == 2){
        ROS_WARN("have no prior about extrinsic param, calibrate extrinsic param");
        RIC.push_back(Eigen::Matrix3d::Identity());
        TIC.push_back(Eigen::Vector3d::Zero());
        fsSettings["ex_calib_result_path"] >> EX_CALIB_RESULT_PATH;
        EX_CALIB_RESULT_PATH = VINS_FOLDER_PATH + EX_CALIB_RESULT_PATH;

    }
    else 
    {
        if ( ESTIMATE_EXTRINSIC == 1){
            ROS_WARN(" Optimize extrinsic param around initial guess!");
            fsSettings["ex_calib_result_path"] >> EX_CALIB_RESULT_PATH;
            EX_CALIB_RESULT_PATH = VINS_FOLDER_PATH + EX_CALIB_RESULT_PATH;
        }
        if (ESTIMATE_EXTRINSIC == 0)
            ROS_WARN(" fix extrinsic param ");

        cv::Mat cv_R, cv_T;
        fsSettings["body_T_cam0"] >> cv_T; 
        Eigen::Matrix4d T; 
        cv::cv2eigen(cv_T, T); 

        RIC.push_back(T.block<3,3>(0,0)); 
        ROS_INFO_STREAM("before normalize Extrinsic_R : " << std::endl << RIC[0]);
        Eigen::Quaterniond Q(RIC[0]); 
        RIC[0] = Q.normalized();
        // ROS_INFO_STREAM(" Q : " << std::endl << Q.w()<<" "<<Q.x()<<" "<<Q.y()<<" "<<Q.z());
        TIC.push_back(T.block<3,1>(0,3));
        ROS_INFO_STREAM("Extrinsic_R : " << std::endl << RIC[0]);
        ROS_INFO_STREAM("Extrinsic_T : " << std::endl << TIC[0].transpose());

        if(NUM_OF_CAM == 2){
            fsSettings["body_T_cam1"] >> cv_T; 
            cv::cv2eigen(cv_T, T); 
            RIC.push_back(T.block<3,3>(0,0)); 
            Eigen::Quaterniond Q(RIC[1]); 
            RIC[1] = Q.normalized();
            TIC.push_back(T.block<3,1>(0,3)); 
            ROS_INFO_STREAM("cam2 Extrinsic_R : " << std::endl << RIC[1]);
            ROS_INFO_STREAM("cam2 Extrinsic_T : " << std::endl << TIC[1].transpose());
        }

    } 

    LOOP_CLOSURE = fsSettings["loop_closure"];
    if (LOOP_CLOSURE == 1)
    {
        fsSettings["voc_file"] >> VOC_FILE;;
        fsSettings["pattern_file"] >> PATTERN_FILE;
        VOC_FILE = VINS_FOLDER_PATH + VOC_FILE;
        PATTERN_FILE = VINS_FOLDER_PATH + PATTERN_FILE;
        MIN_LOOP_NUM = fsSettings["min_loop_num"];
       // CAM_NAMES = config_file;
    }

    RGBD_DPT_MAX = fsSettings["depth_max_dist"];
    RGBD_DPT_MIN = fsSettings["depth_min_dist"];

    CAM_NAMES = config_file;

    S_VERIFY = fsSettings["structure_verify"];
    ENABLE_STRUCTURE = optionalInt(fsSettings, "structure", ENABLE_STRUCTURE);
    USE_GMM = optionalBool(fsSettings, "use_gmm", USE_GMM);
    USE_GMM_EXT = optionalBool(fsSettings, "use_gmm_ext", USE_GMM_EXT);
    ENABLE_PLANE = !optionalBool(fsSettings, "disable_plane", !ENABLE_PLANE);
    ENABLE_LINE = !optionalBool(fsSettings, "disable_line", !ENABLE_LINE);

    n.param("freq_gate", ENABLE_FREQ_GATE, ENABLE_FREQ_GATE);
    n.param("freq", FREQ, FREQ);
    n.param("flow_back", FLOW_BACK, FLOW_BACK);
    n.param("drop_frame", DROP_FRAME, DROP_FRAME);
    n.param("use_gmm", USE_GMM, USE_GMM);
    n.param("use_gmm_ext", USE_GMM_EXT, USE_GMM_EXT);
    bool disable_plane = !ENABLE_PLANE;
    bool disable_line = !ENABLE_LINE;
    n.param("disable_plane", disable_plane, disable_plane);
    n.param("disable_line", disable_line, disable_line);
    n.param("structure", ENABLE_STRUCTURE, ENABLE_STRUCTURE);
    ENABLE_PLANE = !disable_plane;
    ENABLE_LINE = !disable_line;

    if (FREQ < 0 || DROP_FRAME < 0 || (FLOW_BACK != 0 && FLOW_BACK != 1) ||
        (ENABLE_STRUCTURE != 0 && ENABLE_STRUCTURE != 1))
    {
        ROS_FATAL("[PHASE2_FLAGS] invalid flags: freq=%d drop_frame=%d flow_back=%d structure=%d",
                  FREQ, DROP_FRAME, FLOW_BACK, ENABLE_STRUCTURE);
        std::exit(EXIT_FAILURE);
    }
    if (ENABLE_FREQ_GATE && (FREQ <= 0 || DROP_FRAME != 0))
    {
        ROS_FATAL("[PHASE2_FLAGS] freq_gate requires freq>0 and drop_frame=0 (freq=%d drop_frame=%d)", FREQ, DROP_FRAME);
        std::exit(EXIT_FAILURE);
    }
    if (USE_GMM_EXT && !USE_GMM)
    {
        ROS_FATAL("[PHASE2_FLAGS] use_gmm_ext=1 is incompatible with use_gmm=0");
        std::exit(EXIT_FAILURE);
    }
    if (ENABLE_STRUCTURE && !ENABLE_PLANE)
    {
        ROS_FATAL("[PHASE2_FLAGS] structure=1 requires disable_plane=0");
        std::exit(EXIT_FAILURE);
    }

    const char* arm = "custom";
    if (!ENABLE_FREQ_GATE && DROP_FRAME == 0 && FLOW_BACK == 0 && !ENABLE_LINE)
    {
        if (!USE_GMM && !USE_GMM_EXT && !ENABLE_PLANE && !ENABLE_STRUCTURE)
            arm = "A0_simple_point_only";
        else if (USE_GMM && USE_GMM_EXT && !ENABLE_PLANE && !ENABLE_STRUCTURE)
            arm = "A1_gmm_point_only";
        else if (USE_GMM && USE_GMM_EXT && ENABLE_PLANE && !ENABLE_STRUCTURE)
            arm = "A2_gmm_raw_plane";
        else if (USE_GMM && USE_GMM_EXT && ENABLE_PLANE && ENABLE_STRUCTURE)
            arm = "A3_gmm_plane_atlanta";
    }
    ROS_WARN("[PHASE2_EFFECTIVE] arm=%s freq_gate=%d freq=%d drop_frame=%d flow_back=%d use_gmm=%d use_gmm_ext=%d plane=%d line=%d atlanta=%d",
             arm, static_cast<int>(ENABLE_FREQ_GATE), FREQ, DROP_FRAME, FLOW_BACK,
             static_cast<int>(USE_GMM), static_cast<int>(USE_GMM_EXT),
             static_cast<int>(ENABLE_PLANE), static_cast<int>(ENABLE_LINE), ENABLE_STRUCTURE);

    INIT_DEPTH =  5.0; 
    fsSettings.release();
    once = true;
    return ;
}

bool shouldProcessFrameByFrequency(double current_time)
{
    if (!ENABLE_FREQ_GATE)
    {
        PUB_THIS_FRAME = true;
        return true;
    }

    if (first_frequency_frame)
    {
        first_frequency_frame = false;
        first_frequency_time = current_time;
        last_frequency_time = current_time;
        frequency_publish_count = 1;
        PUB_THIS_FRAME = false;
        return false;
    }

    if (current_time < last_frequency_time || current_time - last_frequency_time > 1.0)
    {
        ROS_WARN("[PHASE2_FREQ] timestamp discontinuity; reset frequency gate");
        first_frequency_time = current_time;
        last_frequency_time = current_time;
        frequency_publish_count = 1;
        PUB_THIS_FRAME = false;
        return false;
    }
    last_frequency_time = current_time;

    const double elapsed = current_time - first_frequency_time;
    if (elapsed <= 0.0)
    {
        PUB_THIS_FRAME = false;
        return false;
    }

    const double average_frequency = static_cast<double>(frequency_publish_count) / elapsed;
    PUB_THIS_FRAME = std::round(average_frequency) <= FREQ;
    if (PUB_THIS_FRAME)
    {
        if (std::fabs(average_frequency - FREQ) < 0.01 * FREQ)
        {
            first_frequency_time = current_time;
            frequency_publish_count = 0;
        }
        ++frequency_publish_count;
    }
    return PUB_THIS_FRAME;
}

void logPhase2Counters(bool final_snapshot)
{
    const char* kind = final_snapshot ? "final" : "periodic";
    ROS_WARN("[PHASE2_COUNTERS] kind=%s processed_frames=%llu enqueued_frames=%llu flow_back_checks=%llu gmm_depth_calls=%llu simple_depth_calls=%llu plane_detect_calls=%llu plane_associate_calls=%llu plane_factor_solve=%llu normal_factor_solve=%llu struct_line_factor_solve=%llu plane_factor_margin=%llu normal_factor_margin=%llu struct_line_factor_margin=%llu",
             kind,
             static_cast<unsigned long long>(PHASE2_COUNTERS.processed_frames.load(std::memory_order_relaxed)),
             static_cast<unsigned long long>(PHASE2_COUNTERS.enqueued_frames.load(std::memory_order_relaxed)),
             static_cast<unsigned long long>(PHASE2_COUNTERS.flow_back_checks.load(std::memory_order_relaxed)),
             static_cast<unsigned long long>(PHASE2_COUNTERS.gmm_depth_calls.load(std::memory_order_relaxed)),
             static_cast<unsigned long long>(PHASE2_COUNTERS.simple_depth_calls.load(std::memory_order_relaxed)),
             static_cast<unsigned long long>(PHASE2_COUNTERS.plane_detect_calls.load(std::memory_order_relaxed)),
             static_cast<unsigned long long>(PHASE2_COUNTERS.plane_associate_calls.load(std::memory_order_relaxed)),
             static_cast<unsigned long long>(PHASE2_COUNTERS.plane_factor_solve.load(std::memory_order_relaxed)),
             static_cast<unsigned long long>(PHASE2_COUNTERS.normal_factor_solve.load(std::memory_order_relaxed)),
             static_cast<unsigned long long>(PHASE2_COUNTERS.struct_line_factor_solve.load(std::memory_order_relaxed)),
             static_cast<unsigned long long>(PHASE2_COUNTERS.plane_factor_margin.load(std::memory_order_relaxed)),
             static_cast<unsigned long long>(PHASE2_COUNTERS.normal_factor_margin.load(std::memory_order_relaxed)),
             static_cast<unsigned long long>(PHASE2_COUNTERS.struct_line_factor_margin.load(std::memory_order_relaxed)));
}
