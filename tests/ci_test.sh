#! /usr/bin/env bash
#! -*- coding: utf-8 -*-

################################################
# Don't delete this file or rename it.
# Used by the test suite to run the tests.
# Also used by Github Action to run the tests.
################################################

python3 -c "import sys; print(sys.version)"
if [ $? -ne 0 ]; then
    exit 1
fi

pip3 install -U pip setuptools
pip3 install -r requirements.txt -r requirements-test.txt
pip3 list
pytest -sx -vvv --cov=. tests/
