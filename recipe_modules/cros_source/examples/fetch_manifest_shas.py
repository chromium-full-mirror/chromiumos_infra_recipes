# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'cros_infra_config',
    'cros_source',
    'git',
    'test_util',
]


def RunSteps(api):
  config = api.cros_infra_config.configure_builder()

  count = 10
  api.assertions.assertEqual(
      api.cros_source.fetch_snapshot_shas(count=count),
      api.git.test_api.generate_test_ids(count=count))


def GenTests(api):
  yield api.test('basic',
                 api.test_util.test_child_build('amd64-generic', cq=True).build)
