"""tradelab init-strategy scaffolding tests."""
from __future__ import annotations

from pathlib import Path

import pytest
import typer

from tradelab import cli_init


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """Build a minimal tradelab repo skeleton in tmp_path."""
    (tmp_path / "src" / "tradelab" / "strategies").mkdir(parents=True)
    (tmp_path / "tradelab.yaml").write_text(
        "paths:\n  data_dir: ./_d\n  reports_dir: ./_r\n  cache_dir: ./_c\n"
        "strategies:\n  s2_pocket_pivot:\n"
        "    module: x\n    class_name: X\n    status: ported\n"
    )
    monkeypatch.chdir(tmp_path)
    yield tmp_path


def test_init_creates_simple_strategy_file(repo):
    cli_init.init_strategy(name="my_test_strategy", type="simple",
                            description="my test", register=True, force=False)
    f = repo / "src" / "tradelab" / "strategies" / "my_test_strategy.py"
    assert f.exists()
    content = f.read_text()
    assert "class MyTestStrategy(SimpleStrategy)" in content
    assert 'name = "my_test_strategy"' in content
    assert "def entry_signal" in content


def test_init_creates_advanced_strategy_file(repo):
    cli_init.init_strategy(name="adv_test", type="advanced",
                            description="adv", register=False, force=False)
    f = repo / "src" / "tradelab" / "strategies" / "adv_test.py"
    assert f.exists()
    content = f.read_text()
    assert "class AdvTest(Strategy)" in content
    assert "def generate_signals" in content


def test_init_appends_to_yaml(repo):
    cli_init.init_strategy(name="yaml_test", type="simple",
                            description="yaml ok", register=True, force=False)
    yaml = (repo / "tradelab.yaml").read_text()
    assert "yaml_test:" in yaml
    assert "tradelab.strategies.yaml_test" in yaml
    assert "YamlTest" in yaml


def test_init_refuses_to_overwrite_without_force(repo):
    cli_init.init_strategy(name="dup", type="simple",
                            description="", register=False, force=False)
    with pytest.raises(typer.Exit):
        cli_init.init_strategy(name="dup", type="simple",
                                description="", register=False, force=False)


def test_init_force_overwrites(repo):
    cli_init.init_strategy(name="overwrite_me", type="simple",
                            description="v1", register=False, force=False)
    cli_init.init_strategy(name="overwrite_me", type="advanced",
                            description="v2", register=False, force=True)
    content = (repo / "src" / "tradelab" / "strategies" / "overwrite_me.py").read_text()
    assert "class OverwriteMe(Strategy)" in content   # advanced template


def test_init_invalid_name_exits(repo):
    with pytest.raises(typer.Exit):
        cli_init.init_strategy(name="123_starts_with_digit", type="simple",
                                description="", register=False, force=False)


def test_init_invalid_type_exits(repo):
    with pytest.raises(typer.Exit):
        cli_init.init_strategy(name="ok", type="bogus",
                                description="", register=False, force=False)


def test_init_normalizes_name_case_and_dashes(repo):
    cli_init.init_strategy(name="My-Cool-Strat", type="simple",
                            description="", register=False, force=False)
    f = repo / "src" / "tradelab" / "strategies" / "my_cool_strat.py"
    assert f.exists()
    assert "class MyCoolStrat(SimpleStrategy)" in f.read_text()


def test_generated_simple_file_is_importable(repo, monkeypatch):
    """The generated file should be syntactically valid Python."""
    cli_init.init_strategy(name="syntax_check", type="simple",
                            description="ok", register=False, force=False)
    f = repo / "src" / "tradelab" / "strategies" / "syntax_check.py"
    # Compile-check (no need to import, which would require sys.path setup)
    compile(f.read_text(), str(f), "exec")


def test_generated_advanced_file_is_importable(repo):
    cli_init.init_strategy(name="syntax_adv", type="advanced",
                            description="ok", register=False, force=False)
    f = repo / "src" / "tradelab" / "strategies" / "syntax_adv.py"
    compile(f.read_text(), str(f), "exec")
