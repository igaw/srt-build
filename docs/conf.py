# SPDX-License-Identifier: GPL-2.0-only
"""Sphinx configuration of the srt-build documentation."""

import os
import sys

# srt-build runs from the checkout, it isn't installed
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

project = "srt-build"
author = "Daniel Wagner"
copyright = "Daniel Wagner"

extensions = ["sphinxarg.ext"]
source_suffix = [".rst"]
master_doc = "index"
language = "en"
exclude_patterns = ["_build"]
pygments_style = "sphinx"

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
html_css_files = ["theme_overrides.css"]
