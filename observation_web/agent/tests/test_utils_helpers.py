"""Tests for utils/helpers.py — run_command, tail_file, parse_key_value, safe_int/float."""
import os
import tempfile
import pytest
from observation_points.utils.helpers import (
    run_command, tail_file, parse_key_value,
    safe_int, safe_float, read_sysfs,
)


class TestRunCommand:
    def test_basic_echo(self):
        code, stdout, stderr = run_command("echo hello", shell=True)
        assert code == 0
        assert "hello" in stdout

    def test_nonexistent_command(self):
        code, stdout, stderr = run_command("nonexistent_cmd_12345", shell=True)
        assert code != 0

    def test_timeout(self):
        code, stdout, stderr = run_command("sleep 10", shell=True, timeout=1)
        assert code == -1
        assert "Timeout" in stderr or "timeout" in stderr.lower()

    def test_list_command(self):
        code, stdout, stderr = run_command(["echo", "test"])
        assert code == 0
        assert "test" in stdout

    def test_string_without_shell_splits(self):
        code, stdout, stderr = run_command("echo test", shell=False)
        assert code == 0


class TestTailFile:
    def test_nonexistent_file(self):
        lines, pos = tail_file("/nonexistent/path/file.log")
        assert lines == []
        assert pos == 0

    def test_basic_read(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write("line1\nline2\nline3\n")
            f.flush()
            fname = f.name
        try:
            lines, pos = tail_file(fname)
            assert len(lines) == 3
            assert pos > 0
        finally:
            os.unlink(fname)

    def test_incremental_read(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write("line1\nline2\n")
            f.flush()
            fname = f.name
        try:
            lines1, pos1 = tail_file(fname)
            assert len(lines1) == 2
            with open(fname, "a") as f:
                f.write("line3\n")
            lines2, pos2 = tail_file(fname, last_position=pos1)
            assert len(lines2) == 1
            assert "line3" in lines2[0]
        finally:
            os.unlink(fname)

    def test_skip_existing(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write("line1\nline2\n")
            f.flush()
            fname = f.name
        try:
            lines, pos = tail_file(fname, skip_existing=True)
            assert lines == []
            assert pos > 0
        finally:
            os.unlink(fname)

    def test_file_rotation_detection(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.write("a" * 1000 + "\n")
            f.flush()
            fname = f.name
        try:
            _, pos1 = tail_file(fname)
            with open(fname, "w") as f:
                f.write("new\n")
            lines, pos2 = tail_file(fname, last_position=pos1)
            assert pos2 < pos1
        finally:
            os.unlink(fname)

    def test_max_lines_limit(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            for i in range(100):
                f.write(f"line{i}\n")
            f.flush()
            fname = f.name
        try:
            lines, pos = tail_file(fname, max_lines=10)
            assert len(lines) == 10
        finally:
            os.unlink(fname)

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False) as f:
            f.flush()
            fname = f.name
        try:
            lines, pos = tail_file(fname)
            assert lines == []
        finally:
            os.unlink(fname)


class TestParseKeyValue:
    def test_basic(self):
        text = "key1: value1\nkey2: value2"
        result = parse_key_value(text)
        assert result["key1"] == "value1"
        assert result["key2"] == "value2"

    def test_custom_separator(self):
        text = "key1=value1\nkey2=value2"
        result = parse_key_value(text, sep="=")
        assert result["key1"] == "value1"

    def test_skip_lines_without_sep(self):
        text = "key1: value1\nno separator here\nkey2: value2"
        result = parse_key_value(text)
        assert len(result) == 2

    def test_empty_input(self):
        result = parse_key_value("")
        assert result == {}

    def test_multiple_colons(self):
        text = "time: 12:30:00"
        result = parse_key_value(text)
        assert result["time"] == "12:30:00"


class TestSafeConversions:
    def test_safe_int_normal(self):
        assert safe_int("42") == 42

    def test_safe_int_none(self):
        assert safe_int(None) == 0

    def test_safe_int_invalid(self):
        assert safe_int("abc") == 0

    def test_safe_int_custom_default(self):
        assert safe_int("abc", default=-1) == -1

    def test_safe_float_normal(self):
        assert safe_float("3.14") == pytest.approx(3.14)

    def test_safe_float_none(self):
        assert safe_float(None) == 0.0

    def test_safe_float_invalid(self):
        assert safe_float("xyz") == 0.0

    def test_safe_float_custom_default(self):
        assert safe_float("xyz", default=-1.0) == -1.0


class TestReadSysfs:
    def test_nonexistent_path(self):
        assert read_sysfs("/nonexistent/sysfs/path") is None

    def test_existing_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("42\n")
            f.flush()
            fname = f.name
        try:
            val = read_sysfs(fname)
            assert val is not None
            assert "42" in val
        finally:
            os.unlink(fname)
