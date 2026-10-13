from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "select_erase_method.py"
_spec = importlib.util.spec_from_file_location("select_erase_method", SCRIPT)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
choose_erase_method = _module.choose_erase_method
main = _module.main
UNREPORTED = _module.UNREPORTED


def test_selector_script_matches_the_other_skill():
    here = Path(__file__).resolve()
    repo = here.parents[2]
    rook = (repo / "openshift-rook" / "scripts" / "select_erase_method.py").read_bytes()
    odf = (repo / "openshift-odf" / "scripts" / "select_erase_method.py").read_bytes()
    assert rook == odf


def test_live_controller_with_only_block_erase():
    result = choose_erase_method(
        fna=0,
        sanicap=2,
        crypto_seconds=UNREPORTED,
        block_seconds=UNREPORTED,
        overwrite_seconds=UNREPORTED,
        nn=1,
    )
    assert result["method"] == "sanitize-block"
    assert result["pool"] == "device-media"
    assert result["basis"] == "unmeasured"
    assert result["command"] == "nvme sanitize <controller> --sanact=2 --ause"
    assert result["rejected"] == ["bluestore-offset-wipe"]
    assert "sanitize-overwrite" not in result["considered"]
    assert "full-disk-zero" not in result["considered"]


def test_unreported_key_change_beats_a_timed_block_erase():
    result = choose_erase_method(sanicap=1 | 2, crypto_seconds=UNREPORTED, block_seconds=15)
    assert result["method"] == "sanitize-crypto"
    assert result["seconds"] == 0
    assert result["basis"] == "key-change"
    assert result["pool"] == "key-change"


def test_reported_block_erase_beats_a_slower_reported_key_change():
    result = choose_erase_method(sanicap=1 | 2, crypto_seconds=40, block_seconds=5)
    assert result["method"] == "sanitize-block"
    assert result["basis"] == "reported"
    assert result["seconds"] == 5


def test_reported_overwrite_does_not_replace_an_untimed_block_erase():
    result = choose_erase_method(sanicap=2 | 4, block_seconds=UNREPORTED, overwrite_seconds=8)
    assert result["method"] == "sanitize-block"
    assert result["considered"] == ["sanitize-block"]


def test_shorter_reported_media_erase_wins():
    result = choose_erase_method(sanicap=2, block_seconds=3, secure_erase_minutes=20)
    assert result["method"] == "sanitize-block"
    assert result["seconds"] == 3


def test_zero_seconds_is_a_real_duration():
    result = choose_erase_method(sanicap=2, block_seconds=0, secure_erase_minutes=2)
    assert result["method"] == "sanitize-block"
    assert result["basis"] == "reported"
    assert result["seconds"] == 0


def test_unsupported_crypto_estimate_is_ignored():
    result = choose_erase_method(sanicap=2, crypto_seconds=0)
    assert result["method"] == "sanitize-block"


def test_format_crypto_when_sanitize_crypto_is_absent():
    result = choose_erase_method(fna=4, sanicap=0)
    assert result["method"] == "format-crypto"
    assert result["basis"] == "key-change"
    assert "--ses=2" in result["command"]


def test_measured_controller_blanks_with_sanitize_crypto():
    result = choose_erase_method(
        fna=4,
        sanicap=3,
        crypto_seconds=UNREPORTED,
        block_seconds=UNREPORTED,
        overwrite_seconds=UNREPORTED,
        nn=1,
    )
    assert result["method"] == "sanitize-crypto"
    assert result["basis"] == "key-change"
    assert "format-crypto" in result["considered"]
    assert "sanitize-block" in result["considered"]


def test_sanitize_crypto_wins_a_tie_with_format_crypto():
    result = choose_erase_method(fna=4, sanicap=1, crypto_seconds=UNREPORTED)
    assert result["method"] == "sanitize-crypto"
    assert result["considered"] == ["sanitize-crypto", "format-crypto"]


def test_no_device_erase_uses_the_faster_rewrite():
    result = choose_erase_method(fna=0, sanicap=4, overwrite_seconds=12, zero_seconds=4000)
    assert result["method"] == "sanitize-overwrite"
    assert result["pool"] == "rewrite"
    assert result["seconds"] == 12


def test_nothing_supported_is_a_full_disk_zero():
    result = choose_erase_method(fna=0, sanicap=0)
    assert result["method"] == "full-disk-zero"
    assert "bluestore-offset-wipe" in result["rejected"]


def test_sata_picks_the_shorter_reported_time():
    fast_secure = choose_erase_method(secure_erase_minutes=1, enhanced_erase_minutes=10)
    fast_enhanced = choose_erase_method(secure_erase_minutes=20, enhanced_erase_minutes=2)
    assert fast_secure["method"] == "sata-secure"
    assert fast_secure["seconds"] == 60
    assert fast_enhanced["method"] == "sata-enhanced"
    assert fast_enhanced["seconds"] == 120


def test_extrapolated_zero_does_not_replace_block_erase():
    result = choose_erase_method(sanicap=2, block_seconds=UNREPORTED, zero_seconds=4000)
    assert result["method"] == "sanitize-block"


def test_more_than_one_namespace_is_refused():
    with pytest.raises(ValueError, match="nn must be 1"):
        choose_erase_method(nn=2, sanicap=2)


def test_advertised_write_zeroes_use_blkdiscard():
    result = choose_erase_method(device_class="virtio", write_zeroes_max_bytes=1048576)
    assert result["method"] == "write-zeroes"
    assert result["command"] == "blkdiscard --zeroout <disk>"
    assert result["pool"] == "device-media"
    assert "fstrim" not in result["considered"]


def test_discard_without_write_zeroes_is_not_a_blank():
    result = choose_erase_method(write_zeroes_max_bytes=0, zero_seconds=30)
    assert result["method"] == "full-disk-zero"
    assert result["note"] == ""


def test_write_zeroes_beats_an_extrapolated_full_disk_zero():
    result = choose_erase_method(device_class="virtual", write_zeroes_max_bytes=1048576, zero_seconds=4000)
    assert result["method"] == "write-zeroes"


def test_generic_virtual_disk_writes_zeroes():
    result = choose_erase_method(device_class="virtual", write_zeroes_max_bytes=0)
    assert result["method"] == "full-disk-zero"
    assert result["device_class"] == "virtual"
    assert result["note"] == "writing zeroes is the blank for this virtual disk"
    assert "sanitize-block" not in result["considered"]


def test_virtio_without_write_zeroes_writes_zeroes():
    result = choose_erase_method(device_class="virtio", write_zeroes_max_bytes=0, sanicap=3, fna=4)
    assert result["method"] == "full-disk-zero"
    assert "sanitize-crypto" not in result["considered"]
    assert "format-crypto" not in result["considered"]


def test_nvme_sanitize_beats_write_zeroes():
    result = choose_erase_method(device_class="nvme", sanicap=2, write_zeroes_max_bytes=1048576)
    assert result["method"] == "sanitize-block"


def test_unknown_device_class_is_refused():
    with pytest.raises(ValueError, match="device_class"):
        choose_erase_method(device_class="ide")


def test_cli_prints_the_live_controller_choice(capsys):
    exit_code = main(
        [
            "--fna",
            "0",
            "--sanicap",
            "2",
            "--nn",
            "1",
            "--crypto-seconds",
            str(UNREPORTED),
            "--block-seconds",
            str(UNREPORTED),
            "--overwrite-seconds",
            str(UNREPORTED),
        ]
    )
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["method"] == "sanitize-block"


def test_cli_refuses_multiple_namespaces(capsys):
    exit_code = main(["--nn", "2", "--sanicap", "2"])
    assert exit_code == 2
    assert "nn must be 1" in capsys.readouterr().err
