# pipx-repository-browser

Browse curated Python package repositories and manage installations with pipx.

## Upload to PYPI

```bash
pip install --upgrade pkginfo twine packaging

cd src
python -m build
twine upload dist/*
```
