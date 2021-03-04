# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/file',
    'cros_version',
]


def RunSteps(api):
  api.cros_version.bump_version()


def GenTests(api):
  yield api.test(
      'basic',
      api.buildbucket.ci_build(
          project='chromeos',
          bucket='release',
          builder='main-release-orchestrator',
      ))
