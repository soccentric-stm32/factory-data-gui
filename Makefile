#
# Makefile - Run, check and test the Factory Data GUI
#
# Author:  Sandesh Ghimire <sandesh@soccentric.com>
#
#   make gui       launch the GUI (factory_data_gui.py)
#   make deps      install the dependencies (PySide6) in the virtualenv
#   make venv      create the virtualenv only
#   make check     byte-compile the GUI and the core
#   make test      run the Python tests
#   make lint      ruff check
#   make dist      build the package for the current OS (packaging/)
#   make samples   regenerate examples/*.csv from the built-in samples
#   make help      list these targets
#
# The interpreter is the project virtualenv when it exists and the system
# Python otherwise: Windows puts it in $(VENV)/Scripts/python.exe, macOS and
# Linux in $(VENV)/bin/python.  Override it with `make PYTHON=...`.
#

# Windows: run every recipe under Git's POSIX sh, also from cmd.exe or
# PowerShell with only Git\cmd on PATH. Otherwise native make falls back to
# cmd.exe, which cannot run the recipes (quotes, pipes, find, rm -rf), and
# `sh scripts/...` is not found. Git's usr\bin goes first on PATH so find,
# sort and friends are the POSIX tools, not the Windows ones of the same name.
ifeq ($(OS),Windows_NT)
ifneq ($(origin SHELL),command line)
GIT_USR_BIN := $(firstword \
  $(if $(wildcard C:/Program?Files/Git/usr/bin/sh.exe),C:/Program?Files/Git/usr/bin) \
  $(if $(wildcard $(subst \,/,$(LOCALAPPDATA))/Programs/Git/usr/bin/sh.exe),$(subst \,/,$(LOCALAPPDATA))/Programs/Git/usr/bin) \
  $(if $(wildcard C:/msys64/usr/bin/sh.exe),C:/msys64/usr/bin))
ifneq ($(GIT_USR_BIN),)
SHELL := $(subst ?, ,$(GIT_USR_BIN))/sh.exe
export PATH := $(subst /,\,$(subst ?, ,$(GIT_USR_BIN)));$(PATH)
endif
endif
endif

VENV ?= .venv

# The OS selects the interpreter layout and the packaging script.  uname is
# only asked on macOS and Linux; Windows sets OS=Windows_NT in the environment.
ifeq ($(OS),Windows_NT)
VENV_PYTHON := $(VENV)/Scripts/python.exe
SYS_PYTHON  ?= python
DIST_CMD = powershell -NoProfile -ExecutionPolicy Bypass -File packaging/build-windows.ps1
else
VENV_PYTHON := $(VENV)/bin/python
SYS_PYTHON  ?= python3
ifeq ($(shell uname -s),Darwin)
DIST_CMD = bash packaging/build-macos.sh
else
DIST_CMD = bash packaging/build-linux.sh
endif
endif

# Recursively expanded: a target that builds the venv is seen by the targets
# that run after it, and PYTHON from the environment or the command line wins.
PYTHON ?= $(or $(wildcard $(VENV_PYTHON)),$(SYS_PYTHON))

.PHONY: gui deps venv check test lint dist samples help

gui: check
	"$(PYTHON)" factory_data_gui.py

$(VENV_PYTHON):
	"$(SYS_PYTHON)" -m venv --system-site-packages $(VENV)

venv: $(VENV_PYTHON)

deps: $(VENV_PYTHON)
	"$(PYTHON)" -m pip install -r requirements.txt

check:
	"$(PYTHON)" -m py_compile factory_data_gui.py $(wildcard core/*.py) $(wildcard gui/*.py)

test: check
	"$(PYTHON)" -m pytest -q tests

lint:
	"$(PYTHON)" -m ruff check .

# The packaging scripts are the build; see packaging/README.md.  The version
# they read from gui/window.py names the bundle and the artifact.
dist: check
	PYTHON="$(PYTHON)" $(DIST_CMD)

samples:
	"$(PYTHON)" -c "from core.generators import GENERATORS; \
	[open('examples/%s.csv' % k, 'w', encoding='utf-8', newline='\n').write(g.sample()) \
	for k, g in GENERATORS.items()]"

.DEFAULT_GOAL := help

help:
	@sed -n "/^#   make/p" Makefile | sed "s/^#//"
