# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto.build import Build
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'auto_retry_util',
    'git_footers',
]



def RunSteps(api):
  build = Build(
      id=123,
      input=Build.Input(
          gerrit_changes=[
              GerritChange(
                  host='chromium.googlesource.com',
                  project='projectA',
                  change=456,
                  patchset=1,
              ),
          ],
      ),
  )

  disallow = api.auto_retry_util.no_retry_footer_set(build)
  api.assertions.assertEqual(api.properties['expected_disallow'], disallow)


def GenTests(api):
  yield api.test(
      'test-footers',
      api.properties(expected_disallow=True),
      api.git_footers.simulated_get_footers(['None'], ''),
      api.post_process(post_process.DropExpectation),
  )
