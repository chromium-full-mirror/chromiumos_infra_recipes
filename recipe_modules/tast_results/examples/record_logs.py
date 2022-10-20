# -*- coding: utf-8 -*-

# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'tast_results',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  api.tast_results.record_logs('/var/log')


def GenTests(api):
  yield api.test('basic')
