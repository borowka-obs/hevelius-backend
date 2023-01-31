To run backend locally, run:

```shell
export PYTHONPATH=.:..
cd flask/
python3 -m flask run
```


## Useful developer tasks

1. Check code with pylint: `pylint --rcfile .pylint $(git ls-files 'station/*.py')`

2. Check code with flake8: `flake8 --config .flake8 --color=auto $(git ls-files '*.py')`

3. Fix trivial esthetics in the code: `autopep8 --in-place --max-line-length 160 --aggressive --aggressive $(git ls-files '*.py')`
