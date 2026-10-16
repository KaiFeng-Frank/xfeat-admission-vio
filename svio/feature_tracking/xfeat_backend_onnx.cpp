// onnxruntime (C API) reliability backend for desktop runs of the online path.

#include "xfeat_online.h"

#include <onnxruntime_c_api.h>

#include <stdexcept>

namespace xfeat_online
{
namespace
{
class OnnxBackend : public ReliabilityBackend
{
public:
    OnnxBackend(const std::string &model_path, int cpu_threads)
        : api_(OrtGetApiBase()->GetApi(ORT_API_VERSION)), threads_(cpu_threads), input_(kHeight * kWidth)
    {
        if (api_ == nullptr)
            throw std::runtime_error("onnxruntime library older than the header it was built against");
        check(api_->CreateEnv(ORT_LOGGING_LEVEL_WARNING, "xfeat_online", &env_));
        OrtSessionOptions *options = nullptr;
        check(api_->CreateSessionOptions(&options));
        check(api_->SetIntraOpNumThreads(options, cpu_threads));
        check(api_->SetInterOpNumThreads(options, 1));
        check(api_->SetSessionExecutionMode(options, ORT_SEQUENTIAL));
        OrtStatus *status = api_->CreateSession(env_, model_path.c_str(), options, &session_);
        api_->ReleaseSessionOptions(options);
        check(status);
        check(api_->CreateCpuMemoryInfo(OrtArenaAllocator, OrtMemTypeDefault, &memory_));

        OrtAllocator *allocator = nullptr;
        check(api_->GetAllocatorWithDefaultOptions(&allocator));
        size_t inputs = 0, outputs = 0;
        check(api_->SessionGetInputCount(session_, &inputs));
        check(api_->SessionGetOutputCount(session_, &outputs));
        char *input_name = nullptr, *output_name = nullptr;
        check(api_->SessionGetInputName(session_, 0, allocator, &input_name));
        check(api_->SessionGetOutputName(session_, 0, allocator, &output_name));
        const std::string in_name(input_name), out_name(output_name);
        check(api_->AllocatorFree(allocator, input_name));
        check(api_->AllocatorFree(allocator, output_name));
        if (inputs != 1 || outputs != 1 || in_name != "gray" || out_name != "reliability")
            throw std::runtime_error("expected gray -> reliability model: " + model_path);
        describe_ = "onnxruntime threads=" + std::to_string(threads_) + " model=" + model_path;
    }

    ~OnnxBackend() override
    {
        if (memory_)
            api_->ReleaseMemoryInfo(memory_);
        if (session_)
            api_->ReleaseSession(session_);
        if (env_)
            api_->ReleaseEnv(env_);
    }

    void run(const uint8_t *gray, float *reliability) override
    {
        for (int i = 0; i < kHeight * kWidth; ++i)
            input_[i] = static_cast<float>(gray[i]);
        const int64_t in_shape[4] = {1, 1, kHeight, kWidth};
        const int64_t out_shape[4] = {1, 1, kCellsY, kCellsX};
        OrtValue *in = nullptr, *out = nullptr;
        check(api_->CreateTensorWithDataAsOrtValue(memory_, input_.data(), input_.size() * sizeof(float),
                                                   in_shape, 4, ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT, &in));
        OrtStatus *status = api_->CreateTensorWithDataAsOrtValue(memory_, reliability, kCells * sizeof(float),
                                                                 out_shape, 4, ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT, &out);
        if (status == nullptr)
        {
            const char *in_names[1] = {"gray"};
            const char *out_names[1] = {"reliability"};
            status = api_->Run(session_, nullptr, in_names, &in, 1, out_names, 1, &out);
        }
        if (out)
            api_->ReleaseValue(out);
        api_->ReleaseValue(in);
        check(status);
    }

    std::string describe() const override { return describe_; }

private:
    void check(OrtStatus *status) const
    {
        if (status == nullptr)
            return;
        const std::string message = api_->GetErrorMessage(status);
        api_->ReleaseStatus(status);
        throw std::runtime_error("onnxruntime: " + message);
    }

    const OrtApi *api_;
    int threads_;
    OrtEnv *env_ = nullptr;
    OrtSession *session_ = nullptr;
    OrtMemoryInfo *memory_ = nullptr;
    std::vector<float> input_;
    std::string describe_;
};
}  // namespace

std::unique_ptr<ReliabilityBackend> makeOnnxBackend(const std::string &model_path, int cpu_threads)
{
    return std::unique_ptr<ReliabilityBackend>(new OnnxBackend(model_path, cpu_threads));
}

}  // namespace xfeat_online
