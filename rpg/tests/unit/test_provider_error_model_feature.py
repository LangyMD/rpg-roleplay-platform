"""agents/provider_errors.py 新增两类分类:模型不可用(404/model_not_found 等) 与
功能不支持(400 + "is not enabled for",覆盖 Gemini 工具调用/系统指令被拒)。
两类都是重试无法恢复,必须给可换模型的可行动文案,不能穿透进泛化「请重试」。"""
from agents.provider_errors import classify_provider_error


def test_classify_model_not_found_by_status():
    class _E(Exception):
        status_code = 404
    cat, msg = classify_provider_error(_E("no such route"))
    assert cat == "model_unavailable"
    assert "unavailable" in msg
    assert "no such route" not in msg


def test_classify_model_not_found_openai_marker():
    # OpenAI 错误码 model_not_found,状态码可能被 SDK 吞掉,靠消息短语兜住
    msg_exc = RuntimeError(
        "Error code: 404 - {'error': {'message': 'The model `gpt-9` does not exist', "
        "'type': 'invalid_request_error', 'code': 'model_not_found'}}"
    )
    cat, msg = classify_provider_error(msg_exc)
    assert cat == "model_unavailable"
    assert "gpt-9" not in msg


def test_classify_model_not_found_for_account_marker():
    # 中转站/聚合站常见措辞:模型不在该账户可用列表内
    cat, msg = classify_provider_error(
        RuntimeError("Model claude-x-max not found for account")
    )
    assert cat == "model_unavailable"
    assert "Settings" in msg


def test_classify_feature_unsupported_gemini_system_instruction():
    class _E(Exception):
        status_code = 400
    cat, msg = classify_provider_error(
        _E("Developer instruction is not enabled for models/gemini-legacy")
    )
    assert cat == "feature_unsupported"
    assert "tool calls" in msg or "system instructions" in msg
    assert "gemini-legacy" not in msg


def test_classify_feature_unsupported_gemini_function_calling():
    class _E(Exception):
        status_code = 400
    cat, msg = classify_provider_error(
        _E("Function calling is not enabled for this model")
    )
    assert cat == "feature_unsupported"


def test_feature_unsupported_requires_400_not_other_status():
    # "is not enabled for" 措辞若不是 400,不应命中 feature_unsupported(保持窄匹配)
    class _E(Exception):
        status_code = 403
    cat, _ = classify_provider_error(_E("this capability is not enabled for your plan")) or (None, None)
    assert cat != "feature_unsupported"


def test_model_unavailable_does_not_swallow_other_400():
    # 空 assistant / 参数错等其它 400 不能被误判成 model_unavailable
    class _E(Exception):
        status_code = 400
    assert classify_provider_error(_E("Error code: 400 - messages: last message must not be empty")) is None


def test_context_marker_still_wins_over_model_markers_when_both_could_match():
    # 上下文超长分支排在模型分支之前,确保未被本次改动打乱优先级
    class _E(Exception):
        status_code = 400
    real = ("Error code: 400 - {'error': {'message': \"This endpoint's maximum context "
            "length is 32768 tokens. However, you requested about 34964 tokens. "
            "Please reduce the length of either one\", 'code': 400}}")
    cat, _ = classify_provider_error(_E(real))
    assert cat == "context"
