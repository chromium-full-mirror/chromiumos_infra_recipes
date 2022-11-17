# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for uploading mappings to the PVS database.
"""

from recipe_engine import post_process

DEPS = []

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):  #pylint: disable=unused-argument
  pass


def GenTests(api):
  yield api.test('basic', api.post_check(post_process.StatusSuccess))
