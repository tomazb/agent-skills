from pathlib import Path

REFERENCE = (
    Path(__file__).resolve().parents[1] / "references" / "vm-storage-profiles.md"
)


def test_plain_pvc_bind_wait_is_conditional():
    text = REFERENCE.read_text()
    select = text.index("Default-class selection and provisioning are separate checks")
    skip = text.index(
        "Skip the plain PVC bind wait when no general default is expected"
    )
    consumer = text.index("a pod that mounts `default-sc-test-pvc`")
    wait = text.index("oc wait -n odf-vm-smoke pvc/default-sc-test-pvc")
    assert select < skip < consumer < wait
