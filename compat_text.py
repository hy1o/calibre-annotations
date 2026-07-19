#!/usr/bin/env python
# coding: utf-8

from __future__ import (unicode_literals, division, absolute_import,
                        print_function)

from six import binary_type, text_type


class UnicodeDammit(object):
    """
    Minimal compatibility wrapper for the old BeautifulSoup UnicodeDammit API.
    """
    def __init__(self, value):
        if isinstance(value, text_type):
            self.unicode = value
        elif isinstance(value, binary_type):
            self.unicode = value.decode('utf-8', 'replace')
        elif value is None:
            self.unicode = ''
        else:
            self.unicode = text_type(value)
