# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.recipes.chromeos.test_platform.cros_test_postprocess import CrosTestPostprocessRequest

DEPS = [
    'recipe_engine/properties',
]

PROPERTIES = CrosTestPostprocessRequest


def RunSteps(api, properties):
  pass


def GenTests(api):
  yield api.test('basic')
