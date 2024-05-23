# -*- codiing: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for get_eligible_cls function."""
from recipe_engine.post_process import DropExpectation, MustRun, MustRunRE

DEPS = [
    'auto_runner_util',
]


def RunSteps(api):
  api.auto_runner_util.get_eligible_cls()


def GenTests(api):
  yield api.test('basic',
                 api.post_process(MustRunRE, r'Looking for CLs in host .*'),
                 api.post_process(MustRun, 'Filtering CLs with Cq-Depend'),
                 api.post_process(MustRun, 'Filtering Related Chain CLs'),
                 api.post_process(DropExpectation))
