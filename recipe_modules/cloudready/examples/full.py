# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'cloudready',
]

from recipe_engine import post_process

from PB.recipes.chromeos.build_target import ManifestLocation


def RunSteps(api):
  api.cloudready.setup_cloudready_workspace()


def GenTests(api):
  yield api.test('basic')
