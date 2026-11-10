"""lava_api: where the REST API is, taken from the lavacli identity."""

import pytest

from srt_build.lava_api import LavaApi, api_from_lavacli


def write_cfg(tmp_path):
    cfg = tmp_path / "lavacli.yaml"
    cfg.write_text(
        "default:\n  uri: http://lava.lan:10070/RPC2\n  token: abc\n  username: x\n"
        "other:\n  uri: https://lava.example.org/RPC2/\n"
    )
    return str(cfg)


def test_api_from_lavacli(tmp_path):
    path = write_cfg(tmp_path)
    assert api_from_lavacli(path) == ("http://lava.lan:10070/api/v0.2/", "abc")
    assert api_from_lavacli(path, "other") == (
        "https://lava.example.org/api/v0.2/",
        None,
    )


def test_api_from_lavacli_unknown_identity(tmp_path):
    with pytest.raises(KeyError):
        api_from_lavacli(write_cfg(tmp_path), "missing")


def test_from_config_explicit_url():
    api = LavaApi.from_config({"lava-api": "https://lava.example.org/api/v0.2"})
    assert api.base == "https://lava.example.org/api/v0.2/"
    assert api.token is None


def test_rpc_from_lavacli(tmp_path):
    from srt_build.lava_api import rpc_from_lavacli

    rpc = rpc_from_lavacli(write_cfg(tmp_path))
    # ServerProxy keeps the host (with credentials) in a private attribute
    assert rpc._ServerProxy__host == "x:abc@lava.lan:10070"
