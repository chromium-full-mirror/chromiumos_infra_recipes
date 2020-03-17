# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'gce_provider',
]


def RunSteps(api):
  config = api.gce_provider.get_current_config(
      ['chromeos-ci-cq-us-central1-b-x32'])
  api.assertions.assertEqual(len(config.vms), 1)


def GenTests(api):
  yield api.test('basic')
