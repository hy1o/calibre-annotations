#!/usr/bin/env python
# coding: utf-8

from __future__ import (unicode_literals, division, absolute_import,
                        print_function)

import importlib.util
import sys


class DynamicImportError(ImportError):
    pass


def load_source_module(name, path):
    """
    Load a Python source file under ``name``.

    This is the importlib replacement for the removed dynamic source-loading API.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None:
        raise DynamicImportError("Unable to create an import spec for '{0}' from '{1}'".format(name, path))
    if spec.loader is None:
        raise DynamicImportError("Unable to create an import loader for '{0}' from '{1}'".format(name, path))

    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module
