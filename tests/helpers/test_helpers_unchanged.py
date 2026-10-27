from eodh_workflow import checksum


def test_helpers_unchanged():
    """
    src/eodh_workflow/ must match the template release it came from. If this fails, undo your edits
    to that folder, or replace the folder with the one from a template tag. If you choose to fork the
    helpers, delete this test.
    """
    assert checksum.compute() == checksum.recorded()
