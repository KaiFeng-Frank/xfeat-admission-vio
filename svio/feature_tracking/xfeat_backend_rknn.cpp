// RKNN runtime (librknnrt, C API) reliability backend: the backbone on the RK3588 NPU.

#include "xfeat_online.h"

#include <rknn_api.h>

#include <fstream>
#include <iterator>
#include <stdexcept>

namespace xfeat_online
{
namespace
{
rknn_core_mask parseCores(const std::string &cores)
{
    if (cores.empty() || cores == "0_1_2" || cores == "012")
        return RKNN_NPU_CORE_0_1_2;
    if (cores == "0")
        return RKNN_NPU_CORE_0;
    if (cores == "1")
        return RKNN_NPU_CORE_1;
    if (cores == "2")
        return RKNN_NPU_CORE_2;
    if (cores == "0_1" || cores == "01")
        return RKNN_NPU_CORE_0_1;
    if (cores == "auto")
        return RKNN_NPU_CORE_AUTO;
    throw std::runtime_error("unknown NPU core selection '" + cores + "' (0, 1, 2, 0_1, 0_1_2, auto)");
}

class RknnBackend : public ReliabilityBackend
{
public:
    RknnBackend(const std::string &model_path, const std::string &cores)
    {
        std::ifstream in(model_path.c_str(), std::ios::in | std::ios::binary);
        if (!in)
            throw std::runtime_error("cannot open RKNN model: " + model_path);
        model_.assign(std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>());
        check(rknn_init(&ctx_, model_.data(), static_cast<uint32_t>(model_.size()), 0, nullptr), "rknn_init");
        check(rknn_set_core_mask(ctx_, parseCores(cores)), "rknn_set_core_mask");

        rknn_input_output_num io{};
        check(rknn_query(ctx_, RKNN_QUERY_IN_OUT_NUM, &io, sizeof(io)), "query io");
        rknn_tensor_attr input{}, output{};
        input.index = 0;
        output.index = 0;
        check(rknn_query(ctx_, RKNN_QUERY_INPUT_ATTR, &input, sizeof(input)), "query input");
        check(rknn_query(ctx_, RKNN_QUERY_OUTPUT_ATTR, &output, sizeof(output)), "query output");
        if (io.n_input != 1 || io.n_output != 1 || input.n_elems != kHeight * kWidth || output.n_elems != kCells)
            throw std::runtime_error("expected gray[480x640] -> reliability[60x80] RKNN model: " + model_path);
        rknn_sdk_version version{};
        check(rknn_query(ctx_, RKNN_QUERY_SDK_VERSION, &version, sizeof(version)), "query version");
        describe_ = std::string("rknn api=") + version.api_version + " driver=" + version.drv_version +
                    " cores=" + (cores.empty() ? "0_1_2" : cores) + " model=" + model_path;
    }

    ~RknnBackend() override
    {
        if (ctx_)
            rknn_destroy(ctx_);
    }

    void run(const uint8_t *gray, float *reliability) override
    {
        rknn_input input{};
        input.index = 0;
        input.buf = const_cast<uint8_t *>(gray);
        input.size = kHeight * kWidth;
        input.pass_through = 0;
        input.type = RKNN_TENSOR_UINT8;
        input.fmt = RKNN_TENSOR_NHWC;  // one channel: NHWC and NCHW share the layout
        check(rknn_inputs_set(ctx_, 1, &input), "rknn_inputs_set");
        check(rknn_run(ctx_, nullptr), "rknn_run");
        rknn_output output{};
        output.index = 0;
        output.want_float = 1;
        output.is_prealloc = 1;
        output.buf = reliability;
        output.size = kCells * sizeof(float);
        check(rknn_outputs_get(ctx_, 1, &output, nullptr), "rknn_outputs_get");
        rknn_outputs_release(ctx_, 1, &output);
    }

    std::string describe() const override { return describe_; }

private:
    static void check(int ret, const char *what)
    {
        if (ret != RKNN_SUCC)
            throw std::runtime_error(std::string("RKNN ") + what + " failed: " + std::to_string(ret));
    }

    std::vector<char> model_;
    rknn_context ctx_ = 0;
    std::string describe_;
};
}  // namespace

std::unique_ptr<ReliabilityBackend> makeRknnBackend(const std::string &model_path, const std::string &npu_cores)
{
    return std::unique_ptr<ReliabilityBackend>(new RknnBackend(model_path, npu_cores));
}

}  // namespace xfeat_online
