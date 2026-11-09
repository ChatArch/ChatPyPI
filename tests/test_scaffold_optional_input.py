"""Generated opt-in recipe consumes shared typed input without changing root CLI."""
from pathlib import Path
import runpy
import pytest

from click.testing import CliRunner

from chatpypi import PyPICommandError, scaffold_package


def make_example(tmp_path):
    root=tmp_path/"recipe-demo"
    scaffold_package("recipe-demo", root, template="chatarch", include_mkdocs=False, include_workflows=False)
    command=runpy.run_path(str(root/"examples/interactive_input.py"))["example"]
    return root,command


def test_generated_recipe_reuses_count_type(tmp_path):
    root,command=make_example(tmp_path)
    result=CliRunner().invoke(command,["demo","--count","2","-I"])
    assert result.exit_code==0,result.output
    assert result.output=="demo\ndemo\n"
    text=(root/"examples/interactive_input.py").read_text()
    assert "param_type=COUNT" in text
    assert "recursive-include examples *.py" in (root/"MANIFEST.in").read_text()
    assert "@add_interactive_option" not in (root/"src/recipe_demo/cli.py").read_text()


def test_generated_recipe_prompted_count_is_bounded(tmp_path,monkeypatch):
    _,command=make_example(tmp_path)
    monkeypatch.setattr("chatstyle.core.interactive.is_interactive_available",lambda:True)
    result=CliRunner().invoke(command,["demo","-i"],input="11\n")
    assert result.exit_code!=0
    assert "Invalid value for Count" in result.output


@pytest.mark.parametrize("name",["class","for","import","async"])
def test_scaffold_rejects_python_keyword_before_writes(tmp_path,name):
    root=tmp_path/"generated"
    with pytest.raises(PyPICommandError,match="keyword"):
        scaffold_package(name,root,template="chatarch")
    assert not root.exists()
