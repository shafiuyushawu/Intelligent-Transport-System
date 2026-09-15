import shutil

from scripts.validate_project import validate_environment


def test_validate_environment():
    env = validate_environment()
    assert env["sumo"] == shutil.which("sumo")
    assert env["netconvert"] == shutil.which("netconvert")
    assert "SUMO_HOME" in env
    assert "SUMO_TOOLS" in env

