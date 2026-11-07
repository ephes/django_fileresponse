# How to contribute

## How to get started

Use CPython 3.11–3.13 and install the bounded development extra in a virtual
environment:

```sh
python -m pip install -e '.[dev]'
```

Canonical library code and README content live in `nbs/*.ipynb`. After editing,
run `python scripts/generate.py --docs`. This uses nbdev 1.2.11 in a disposable
copy, preserves the site's `/django_fileresponse/` base URL, and renders API docs
without running service demonstrations. Do not run `nbdev_test_nbs` over all
notebooks: MinIO, project creation and bulk download examples are not CI tests.

Run the local CI equivalents listed in README: Ruff, mypy, generated-file parity,
`python -m unittest discover -s tests -v`, `python -m build`, and
`python scripts/package_smoke.py`. The last command checks both distributions in
fresh environments outside the checkout. Use only synthetic fixtures and fake
S3 boundaries. No credentials or external services are needed. No changelog is
currently maintained; document behavior changes in the canonical notebooks.

## Did you find a bug?

* Ensure the bug was not already reported by searching on GitHub under Issues.
* If you're unable to find an open issue addressing the problem, open a new one. Be sure to include a title and clear description, as much relevant information as possible, and a code sample or an executable test case demonstrating the expected behavior that is not occurring.
* Be sure to add the complete error messages.

#### Did you write a patch that fixes a bug?

* Open a new GitHub pull request with the patch.
* Ensure that your PR includes a test that fails without your patch, and pass with it.
* Ensure the PR description clearly describes the problem and solution. Include the relevant issue number if applicable.

## PR submission guidelines

* Keep each PR focused. While it's more convenient, do not combine several unrelated fixes together. Create as many branches as needing to keep each PR focused.
* Do not mix style changes/fixes with "functional" changes. It's very difficult to review such PRs and it most likely get rejected.
* Do not add/remove vertical whitespace. Preserve the original style of the file you edit as much as you can.
* Do not turn an already submitted PR into your development playground. If after you submitted PR, you discovered that more work is needed - close the PR, do the required work and then submit a new PR. Otherwise each of your commits requires attention from maintainers of the project.
* If, however, you submitted a PR and received a request for changes, you should proceed with commits inside that PR, so that the maintainer can see the incremental fixes and won't need to review the whole PR again. In the exception case where you realize it'll take many many commits to complete the requests, then it's probably best to close the PR, do the work and then submit it again. Use common sense where you'd choose one way over another.

## Do you want to contribute to the documentation?

* Docs are automatically created from the notebooks in the nbs folder.

