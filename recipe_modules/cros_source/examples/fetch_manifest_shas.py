# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

DEPS = [
    'recipe_engine/assertions',
    'cros_source',
    'git',
    'test_util',
]



def RunSteps(api):
  _ = api.cros_source.configure_builder(default_main=True)

  count = 10
  api.assertions.assertEqual(
      api.cros_source.fetch_snapshot_shas(count=count),
      api.git.test_api.generate_test_ids(count=count))


def GenTests(api):
  yield api.test('basic',
                 api.test_util.test_child_build('amd64-generic', cq=True).build)
