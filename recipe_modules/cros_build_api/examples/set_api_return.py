# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/step',
    'cros_build_api',
]

from PB.chromite.api import api as meta_api


def RunSteps(api):
  # Create expected = version 0.5555.5555.
  expected = meta_api.VersionGetResponse()
  expected.version.minor = 5555
  expected.version.bug = 5555
  with api.step.nest('test step'):
    api.assertions.assertEqual(
        api.cros_build_api.VersionService.Get(meta_api.VersionGetRequest()),
        expected)


def GenTests(api):
  yield api.test(
      'basic',
      api.cros_build_api.set_api_return(
          'test step', 'VersionService/Get',
          '{"version":{"minor":5555,"bug":5555}}'))
