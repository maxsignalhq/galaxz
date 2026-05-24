import pytest

from workspace.file_writer import FileWriter, WrittenArtifact


def test_write_creates_file_and_returns_valid_artifact(tmp_path):
    writer = FileWriter(str(tmp_path))
    artifact = writer.write("hello.py", "print('hello')\n")

    assert artifact.filename == "hello.py"
    assert artifact.absolute_path == str(tmp_path / "hello.py")
    assert artifact.relative_path == "hello.py"
    assert artifact.size_bytes > 0
    assert (tmp_path / "hello.py").read_text() == "print('hello')\n"


def test_write_creates_missing_parent_directories(tmp_path):
    writer = FileWriter(str(tmp_path))
    artifact = writer.write("subdir/nested/foo.py", "x = 1\n")

    assert (tmp_path / "subdir" / "nested" / "foo.py").exists()
    assert artifact.relative_path == "subdir/nested/foo.py"


def test_infer_filename_code_generation_returns_py_file(tmp_path):
    writer = FileWriter(str(tmp_path))
    result = writer.infer_filename("create a weather app", "code_generation")

    assert result.endswith(".py")
    assert result  # not empty
    assert "weather" in result


def test_infer_filename_empty_description_returns_fallback(tmp_path):
    writer = FileWriter(str(tmp_path))
    result = writer.infer_filename("", "test_writing")

    assert result == "output_test_writing.py"
