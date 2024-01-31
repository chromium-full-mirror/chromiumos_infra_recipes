# -*- coding: utf-8 -*-

# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'tast_results',
]



def RunSteps(api):
  api.tast_results.record_logs('/var/log')


def GenTests(api):
  yield api.test('basic')
