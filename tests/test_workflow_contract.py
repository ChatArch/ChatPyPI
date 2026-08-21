from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_ci_workflow_smokes_shared_tree_options():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )

    assert "python -m chatpypi.cli --version" in workflow
    assert "python -m chatpypi.cli --tree" in workflow
    assert "python -m chatpypi.cli --tree-brief" in workflow


def test_publish_workflow_is_tag_only_and_main_guarded():
    workflow = (ROOT / ".github" / "workflows" / "publish.yml").read_text(
        encoding="utf-8"
    )

    assert "workflow" + "_dispatch:" not in workflow
    assert "tags:" in workflow
    assert '"v*"' in workflow
    assert "if: github.event_name == 'push'" not in workflow
    assert "RELEASE_TAG: ${{ steps.meta.outputs.tag }}" in workflow
    assert 'if [ "${GITHUB_REF_NAME}" != "${RELEASE_TAG}" ]; then' in workflow
    assert "git fetch --no-tags origin main:refs/remotes/origin/main" in workflow
    assert "git merge-base --is-ancestor \"${GITHUB_SHA}\" refs/remotes/origin/main" in workflow
    assert ("git fetch origin main " + "--tags") not in workflow
    assert ("git fetch origin master " + "--tags") not in workflow
    assert "id-token: write" in workflow
    assert "pypa/gh-action-pypi-publish@release/v1" in workflow
    assert ("PYPI" + "_API" + "_TOKEN") not in workflow
    assert ("TWINE" + "_PASSWORD") not in workflow
    assert ("secrets" + ".PYPI") not in workflow
    assert ("environment" + ": pypi") not in workflow


def test_preview_workflow_reads_mkdocs_site_url():
    workflow = (ROOT / ".github" / "workflows" / "preview.yaml").read_text(
        encoding="utf-8"
    )

    assert "git fetch origin gh-pages --depth=1 || true" in workflow
    assert "mike deploy dev --push --update-aliases --allow-empty" in workflow
    assert "Path(\"mkdocs.yml\")" in workflow
    assert "CHATARCH_PREVIEW_URL" in workflow
    assert "https://arch.gh.wzhecnu.cn/${" + "repo}/dev/" not in workflow
    assert ("github" + ".io") not in workflow


def test_mkdocs_material_renderer_is_enabled():
    text = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")

    assert "pymdownx.emoji:" in text
    assert "material.extensions.emoji.twemoji" in text
    assert "material.extensions.emoji.to_svg" in text
