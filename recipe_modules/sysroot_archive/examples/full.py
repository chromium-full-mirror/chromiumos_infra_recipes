# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Test codes for sysroot archive API."""

DEPS = [
    'sysroot_archive',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  del api


def GenTests(api):
  yield api.test('basic')
