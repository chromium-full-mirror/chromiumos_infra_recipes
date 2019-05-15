# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto.build import Build

DEPS = [
    'recipe_engine/assertions',
    'cros_test_plan',
]


def RunSteps(api):
  test_plan = api.cros_test_plan.generate([Build()])


def GenTests(api):
  yield api.test('basic')
