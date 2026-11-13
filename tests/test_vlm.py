from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from smriti import vlm

pytestmark = pytest.mark.unit


def _image(path, size=(8, 8)):
    from PIL import Image

    Image.new("RGB", size, "white").save(path, format="WEBP")


def test_unowned_listener_is_not_reused_or_stopped(monkeypatch):
    monkeypatch.setattr(vlm, "is_vlm_available", lambda: True)
    def busy(port):
        raise vlm.VlmError("qwen_port_busy")

    monkeypatch.setattr(vlm, "_check_port", busy)
    get = Mock()
    spawn = Mock()
    monkeypatch.setattr(vlm.requests, "get", get)
    monkeypatch.setattr(vlm.subprocess, "Popen", spawn)
    events = []
    with pytest.raises(vlm.VlmError, match="qwen_port_busy"):
        with vlm.VlmSession(port=8099, on_event=lambda event, **kw: events.append(event)):
            pytest.fail("Never reuse another process")
    assert events == []
    get.assert_not_called()
    spawn.assert_not_called()


def test_startup_timeout_stops_spawned_process(monkeypatch):
    monkeypatch.setattr(vlm, "is_vlm_available", lambda: True)
    monkeypatch.setattr(vlm, "_check_port", lambda port: None)
    monkeypatch.setattr(vlm.requests, "get", Mock(side_effect=requests.ConnectionError()))
    process = Mock()
    process.poll.return_value = None
    monkeypatch.setattr(vlm.subprocess, "Popen", Mock(return_value=process))
    monkeypatch.setattr(vlm.time, "monotonic", Mock(side_effect=[0, 31]))
    events = []
    session = vlm.VlmSession(on_event=lambda event, **kw: events.append(event))
    with pytest.raises(TimeoutError):
        with session:
            pytest.fail("A timed out server must not enter the body")
    process.terminate.assert_called_once()
    process.wait.assert_called_once()
    assert session.process is None
    assert events == ["operation_failed", "unloading", "unloaded"]


def test_shutdown_timeout_kills_and_waits_before_success(monkeypatch):
    process = Mock()
    process.poll.return_value = None
    process.wait.side_effect = [vlm.subprocess.TimeoutExpired("synthetic", 5), 0]
    events = []
    session = vlm.VlmSession(on_event=lambda event, **kw: events.append(event))
    session.process = process
    session.__exit__(None, None, None)
    process.kill.assert_called_once()
    assert process.wait.call_count == 2
    assert events == ["unloading", "unloaded"]


def test_failed_shutdown_is_not_reported_successfully():
    process = Mock()
    process.poll.return_value = None
    process.terminate.side_effect = OSError("PRIVATE SENTINEL")
    events = []
    session = vlm.VlmSession(on_event=lambda event, **kw: events.append(event))
    session.process = process
    with pytest.raises(vlm.VlmError, match="cleanup_failed"):
        session.__exit__(None, None, None)
    assert events == ["unloading", "cleanup_failed"]
    assert session.process is process


def test_progress_callback_failure_cannot_prevent_cleanup(caplog):
    process = Mock()
    process.poll.return_value = None
    session = vlm.VlmSession(on_event=Mock(side_effect=RuntimeError("PRIVATE SENTINEL")))
    session.process = process
    session.__exit__(RuntimeError, RuntimeError(), None)
    process.terminate.assert_called_once()
    process.wait.assert_called_once()
    assert session.process is None
    assert "PRIVATE SENTINEL" not in caplog.text


def test_inference_requires_active_owned_session_and_uses_its_endpoint(monkeypatch, tmp_path):
    import json

    image = tmp_path / "synthetic.webp"
    _image(image)
    session = vlm.VlmSession(port=8099)
    post = Mock()
    monkeypatch.setattr(vlm.requests, "post", post)
    with pytest.raises(vlm.VlmError, match="qwen_session_inactive"):
        vlm.extract_page_vlm(image, 21, session=session)
    post.assert_not_called()
    session.process = Mock()
    session.process.poll.return_value = None
    session.active = True
    response = Mock()
    response.iter_content.return_value = [json.dumps({"choices": [{"message": {"content": "[]"}}]}).encode()]
    post.return_value = response
    assert vlm.extract_page_vlm(image, 21, session=session) == []
    assert post.call_args.args[0] == "http://127.0.0.1:8099/v1/chat/completions"
    response.close.assert_called_once()


def test_response_capacity_closes_connection_without_parsing_or_truncation(monkeypatch, tmp_path):
    image = tmp_path / "synthetic.webp"
    _image(image)
    session = vlm.VlmSession()
    session.process = Mock()
    session.process.poll.return_value = None
    session.active = True
    response = Mock()
    response.iter_content.return_value = [b"x" * 513]
    monkeypatch.setattr(vlm.requests, "post", Mock(return_value=response))
    with pytest.raises(vlm.VlmError, match="capacity_exhausted"):
        vlm.extract_page_vlm(image, 1, session=session, max_artifact_bytes=512)
    response.close.assert_called_once()


@pytest.mark.parametrize("error,code", [(requests.Timeout, "timeout"), (requests.ConnectionError, "qwen_connection_failed"),
                                      (requests.exceptions.ChunkedEncodingError, "qwen_transfer_failed"),
                                      (requests.RequestException, "qwen_request_failed")])
def test_inference_transport_failures_have_safe_specific_codes(monkeypatch, tmp_path, error, code):
    image = tmp_path / "synthetic.webp"
    _image(image)
    session = vlm.VlmSession()
    session.process = Mock()
    session.process.poll.return_value = None
    session.active = True
    monkeypatch.setattr(vlm.requests, "post", Mock(side_effect=error("PRIVATE_SENTINEL")))
    with pytest.raises(vlm.VlmError) as failed:
        vlm.extract_page_vlm(image, 1, session=session)
    assert failed.value.code == code and "PRIVATE_SENTINEL" not in str(failed.value)


def _inference(monkeypatch, tmp_path, body):
    import json

    image = tmp_path / "synthetic.webp"
    _image(image)
    session = vlm.VlmSession()
    session.process = Mock()
    session.process.poll.return_value = None
    session.active = True
    response = Mock()
    response.iter_content.return_value = [json.dumps(body).encode()]
    monkeypatch.setattr(vlm.requests, "post", Mock(return_value=response))
    return image, session, response


@pytest.mark.parametrize("status", [400, 413, 500, 503])
def test_http_failure_preserves_status_without_body_or_exception(monkeypatch, tmp_path, status):
    image, session, response = _inference(monkeypatch, tmp_path, {"PRIVATE_BODY": "PRIVATE_SENTINEL"})
    response.status_code = status
    response.raise_for_status.side_effect = requests.HTTPError("PRIVATE_SENTINEL")
    with pytest.raises(vlm.VlmError) as failed:
        vlm.extract_page_vlm(image, 1, session=session)
    assert failed.value.code == "qwen_http_error"
    assert failed.value.http_status == status
    assert "PRIVATE" not in str(failed.value)
    response.iter_content.assert_not_called()
    response.close.assert_called_once()


def test_connection_failure_distinguishes_observed_server_exit(monkeypatch, tmp_path):
    image, session, _ = _inference(monkeypatch, tmp_path, {})
    session.process.poll.side_effect = [None, 1]
    monkeypatch.setattr(vlm.requests, "post", Mock(side_effect=requests.ConnectionError("PRIVATE")))
    with pytest.raises(vlm.VlmError, match="qwen_server_exited"):
        vlm.extract_page_vlm(image, 1, session=session)


@pytest.mark.parametrize("output", ["[]", "```json\n[]\n```", '[{"name":"Glucose","value":"90","unit":"mg/dL","reference":"70-100"}]'])
def test_valid_model_arrays_include_explicit_empty_result(monkeypatch, tmp_path, output):
    image, session, response = _inference(monkeypatch, tmp_path, {"choices": [{"message": {"content": output}}]})
    fields = vlm.extract_page_vlm(image, 7, session=session)
    assert len(fields) == (1 if "Glucose" in output else 0)
    if fields:
        assert fields[0].page == 7
    response.close.assert_called_once()


@pytest.mark.parametrize("output", [
    '{"results":[{"name":"Glucose","value":"90","unit":"mg/dL","reference":"70-100"}]}',
    '```json\n{"results":[{"name":"Glucose","value":"90","unit":"mg/dL","reference":"70-100"}]}\n```',
    '{"results":[]}',
])
def test_documented_strict_schema_object_is_accepted(monkeypatch, tmp_path, output):
    image, session, response = _inference(monkeypatch, tmp_path, {"choices": [{"message": {"content": output}}]})
    fields = vlm.extract_page_vlm(image, 4, session=session)
    assert len(fields) == (1 if "Glucose" in output else 0)
    if fields:
        assert fields[0].page == 4 and fields[0].unit_raw == "mg/dL"
    response.close.assert_called_once()


@pytest.mark.parametrize("output", ["PRIVATE_SENTINEL", "[{broken}]", "{}", "[null]", '[{"name":"Glucose"}]', '[{"name":"","value":"90"}]',
                                  '[{"name":"Glucose","value":NaN}]', '[{"name":"Glucose","value":Infinity}]',
                                  '[{"name":"Glucose","value":"NaN"}]', '[{"name":"Glucose","value":"1e999"}]',
                                  '[{"name":"Glucose","value":true}]', '[{"name":"Glucose","value":null}]'])
def test_malformed_model_output_is_not_successful_empty_reading(monkeypatch, tmp_path, output):
    image, session, response = _inference(monkeypatch, tmp_path, {"choices": [{"message": {"content": output}}]})
    with pytest.raises(vlm.VlmError, match="qwen_output_invalid") as failed:
        vlm.extract_page_vlm(image, 1, session=session)
    assert "PRIVATE" not in str(failed.value)
    response.close.assert_called_once()


def test_null_optional_values_are_not_invented_units_or_reference_ranges(monkeypatch, tmp_path):
    image, session, _ = _inference(monkeypatch, tmp_path, {"choices": [{"message": {
        "content": '[{"name":"Glucose","value":90,"unit":null,"reference":null}]',
    }}]})
    field, = vlm.extract_page_vlm(image, 1, session=session)
    assert field.unit_raw is None and field.ref_low is None and field.ref_high is None


@pytest.mark.parametrize("body", [{}, {"choices": []}, {"choices": [{"message": {"content": None}}]}])
def test_invalid_response_envelope_has_specific_safe_code(monkeypatch, tmp_path, body):
    image, session, response = _inference(monkeypatch, tmp_path, body)
    with pytest.raises(vlm.VlmError, match="qwen_response_invalid"):
        vlm.extract_page_vlm(image, 1, session=session)
    response.close.assert_called_once()


@pytest.mark.parametrize("size,expected", [((1600, 2400), (512, 768)), ((100, 200), (100, 200))])
def test_request_resizing_preserves_source_and_budget(monkeypatch, tmp_path, size, expected):
    import base64
    import io
    from PIL import Image

    image, session, _ = _inference(monkeypatch, tmp_path, {"choices": [{"message": {"content": "[]"}}]})
    _image(image, size)
    original = image.read_bytes()
    assert vlm.extract_page_vlm(image, 1, session=session) == []
    kwargs = vlm.requests.post.call_args.kwargs
    assert kwargs["timeout"] == 240 and kwargs["json"]["max_tokens"] == 2048
    url = kwargs["json"]["messages"][0]["content"][0]["image_url"]["url"]
    with Image.open(io.BytesIO(base64.b64decode(url.split(",")[1]))) as sent:
        assert sent.size == expected
    assert image.read_bytes() == original


@pytest.mark.parametrize("kind,code", [("invalid", "prepared_artifact_invalid"), ("pixels", "pixel_limit"), ("bytes", "capacity_exhausted")])
def test_request_input_bounds_precede_http(monkeypatch, tmp_path, kind, code):
    image, session, _ = _inference(monkeypatch, tmp_path, {})
    options = {}
    if kind == "invalid":
        image.write_bytes(b"invalid")
    elif kind == "pixels":
        options["max_pixels"] = 1
    else:
        options["max_artifact_bytes"] = 1
    from smriti.spool import SpoolError

    with pytest.raises((vlm.VlmError, SpoolError)) as failure:
        vlm.extract_page_vlm(image, 1, session=session, **options)
    assert failure.value.code == code
    vlm.requests.post.assert_not_called()


def test_launch_uses_requested_bounded_flags_and_private_output(monkeypatch):
    monkeypatch.setattr(vlm, "is_vlm_available", lambda: True)
    monkeypatch.setattr(vlm, "_check_port", lambda port: None)
    process = Mock()
    process.poll.return_value = None
    spawn = Mock(return_value=process)
    monkeypatch.setattr(vlm.subprocess, "Popen", spawn)
    monkeypatch.setattr(vlm, "_owns_listener", lambda *args: True)
    monkeypatch.setattr(vlm.time, "sleep", lambda *args: None)
    monkeypatch.setattr(vlm.requests, "get", Mock(return_value=SimpleNamespace(status_code=200)))
    with vlm.VlmSession():
        pass
    args = spawn.call_args.args[0]
    for flag, value in [("-c", "1536"), ("-ngl", "99"), ("-t", "4"), ("--parallel", "1"),
                        ("--flash-attn", "off")]:
        assert args[args.index(flag) + 1] == value
    assert "-ctk" in args and args[args.index("-ctk") + 1] == "q8_0"
    assert "-ctv" in args and args[args.index("-ctv") + 1] == "q8_0"
    # The vision projector stays on the GPU: CPU encoding cost 73s vs 8s per page on a 4 GB card.
    assert "--no-mmproj-offload" not in args
    assert {"--no-warmup", "--offline", "--log-disable"} <= set(args)
    assert spawn.call_args.kwargs["stdout"] == spawn.call_args.kwargs["stderr"] == vlm.subprocess.DEVNULL
