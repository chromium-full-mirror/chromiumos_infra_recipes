# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipe_modules.chromeos.skylab.skylab import SkylabProperties

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'skylab',
    'src_state',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  api.src_state.gerrit_changes = api.buildbucket.build.input.gerrit_changes

  actual = api.skylab.direct_tast_testing_enabled()
  expected = api.properties.get('expected', False)
  api.assertions.assertEqual(actual, expected)


def GenTests(api):

  yield api.test(
      'no-allowlist-or-experiment',
      api.buildbucket.try_build(),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no-gerrit-changes',
      api.buildbucket.ci_build(),
      api.properties(
          **{
              '$chromeos/skylab':
                  SkylabProperties(direct_tast_testing_projects=[
                      'chromiumos/chromite', 'chromiumos/infra'
                  ]),
          }),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'experiment',
      api.buildbucket.try_build(
          experiments=['chromeos.skylab.direct_tast_testing']),
      api.properties(
          expected=True,
      ),
      api.post_process(post_process.DropExpectation),
  )

  gc1 = GerritChange(host='chrome-internal-review.googlesource.com',
                     project='chromiumos/infra/config', change=1234)
  gc2 = GerritChange(host='chrome-internal-review.googlesource.com',
                     project='chromiumos/chromite', change=1235)
  yield api.test(
      'allowlisted',
      api.buildbucket.try_build(gerrit_changes=[gc1, gc2]),
      api.properties(
          **{
              '$chromeos/skylab':
                  SkylabProperties(direct_tast_testing_projects=[
                      'chromiumos/chromite', 'chromiumos/infra'
                  ]),
              'expected':
                  True
          }),
      api.post_process(post_process.DropExpectation),
  )

  gc3 = GerritChange(host='chrome-internal-review.googlesource.com',
                     project='chromiumos/something/else')
  yield api.test(
      'not-all-allowlisted',
      api.buildbucket.try_build(gerrit_changes=[gc1, gc2, gc3]),
      api.properties(
          **{
              '$chromeos/skylab':
                  SkylabProperties(direct_tast_testing_projects=[
                      'chromiumos/chromite', 'chromiumos/infra'
                  ]),
              'expected':
                  False
          }),
      api.post_process(post_process.DropExpectation),
  )
