"""jobs hack: the hacking-session job built from an existing job."""

import base64

import yaml

from srt_build.commands.cmd_jobs_hack import find_addresses, hack_definition

SRC = """
actions:
- deploy:
    kernel: {type: image, url: http://x/k-rt}
    to: tftp
- boot: {method: u-boot, commands: nfs}
- test:
    definitions:
    - {from: git, name: svsematest, path: a.yaml, repository: git://x/t.git}
    timeout: {seconds: 180}
device_type: bcm2837-rpi-3-b
job_name: svsematest
tags: [rpi3-64]
timeouts:
  job: {minutes: 5}
  action: {minutes: 5}
"""


def test_keeps_deploy_and_boot_replaces_tests():
    job = yaml.safe_load(hack_definition(SRC, "ssh-ed25519 AAA me", 30))
    kinds = [next(iter(a)) for a in job["actions"]]
    assert kinds == ["deploy", "boot", "test"]
    test = job["actions"][2]["test"]
    assert test["timeout"] == {"minutes": 35}
    (d,) = test["definitions"]
    assert d["from"] == "inline"
    steps = d["repository"]["run"]["steps"]
    assert any("ssh-ed25519 AAA me" in s for s in steps)
    assert any("1800" in s for s in steps)
    assert job["timeouts"]["job"] == {"minutes": 50}
    assert job["timeouts"]["action"] == {"minutes": 5}
    assert job["tags"] == ["rpi3-64"]
    assert job["job_name"] == "hack (svsematest)"


def test_kernel_override():
    job = yaml.safe_load(hack_definition(SRC, "k", 5, kernel="http://x/k-ll"))
    assert job["actions"][0]["deploy"]["kernel"]["url"] == "http://x/k-ll"


def test_files_and_run_come_before_the_wait():
    data = b"#!/bin/sh\necho 'it''s' \"$1\"\n"
    job = yaml.safe_load(
        hack_definition(SRC, "k", 5, files={"t.sh": data}, run="./t.sh x")
    )
    steps = job["actions"][2]["test"]["definitions"][0]["repository"]["run"]["steps"]
    copy = next(s for s in steps if "base64 -d > /root/t.sh" in s)
    assert base64.b64decode(copy.split()[1]) == data
    run = next(i for i, s in enumerate(steps) if "./t.sh x" in s)
    wait = next(i for i, s in enumerate(steps) if s.startswith("while"))
    assert steps.index(copy) < run < wait


def test_find_addresses_dedups():
    log = "SRT_HACK_ADDR=10.0.0.5\nx SRT_HACK_ADDR=10.0.0.5\nSRT_HACK_ADDR=${a%/*}"
    assert find_addresses(log) == ["10.0.0.5"]


def test_kernel_args_are_added():
    src = SRC + "context:\n  extra_kernel_args: systemd.show_status=0\n"
    job = yaml.safe_load(hack_definition(src, "k", 5, kernel_args="nohz_full=1"))
    assert job["context"]["extra_kernel_args"] == "systemd.show_status=0 nohz_full=1"
    job = yaml.safe_load(hack_definition(SRC, "k", 5, kernel_args="nohz_full=1"))
    assert job["context"]["extra_kernel_args"] == "nohz_full=1"
