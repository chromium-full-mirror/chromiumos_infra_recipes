# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipe_modules.chromeos.cros_test_plan_v2.cros_test_plan_v2 import CrosTestPlanV2Properties

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_test_plan_v2',
    'gerrit',
]


gerrit_changes = [
    GerritChange(
        host='chromium-review.googlesource.com',
        project='src/projectA',
        change=123,
        patchset=3,
    ),
    GerritChange(
        host='chromium-review.googlesource.com',
        project='src/project/nestedproject/projectB',
        change=456,
        patchset=7,
    ),
]


def RunSteps(api):
  api.assertions.assertTrue(
      api.cros_test_plan_v2.enabled_on_changes(gerrit_changes))

  with api.assertions.assertRaisesRegexp(ValueError,
                                         'gerrit_changes must be non-empty'):
    api.cros_test_plan_v2.enabled_on_changes([])


def GenTests(api):

  yield api.test(
      'files-in-allowlist',
      api.properties(
          **{
              '$chromeos/cros_test_plan_v2':
                  CrosTestPlanV2Properties(migration_configs=[
                      CrosTestPlanV2Properties.ProjectMigrationConfig(
                          host='chromium-review.googlesource.com',
                          project='src/projectA',
                          file_allowlist_regexps=['a/b/.*'],
                          file_blocklist_regexps=['a/b/d/otherfile.json'],
                          branch_allowlist_regexps=['.*'],
                      ),
                      CrosTestPlanV2Properties.ProjectMigrationConfig(
                          host='chromium-review.googlesource.com',
                          project='src/project/.*',
                          file_allowlist_regexps=['test.json'],
                          branch_allowlist_regexps=['.*'],
                      )
                  ])
          }),
      api.gerrit.set_gerrit_fetch_changes_response(
          'check test planning v2 enabled', [gerrit_changes[0]], {
              123: {
                  'patch_set': 3,
                  'files': {
                      'a/b/d/test.txt': {},
                  }
              },
          }, iteration=1),
      api.gerrit.set_gerrit_fetch_changes_response(
          'check test planning v2 enabled', [gerrit_changes[1]], {
              456: {
                  'patch_set': 7,
                  'files': {
                      'test.json': {},
                  }
              },
          }, iteration=2),
      api.post_process(post_process.StepTextEquals,
                       'check test planning v2 enabled',
                       'enabling test planning v2'),
  )

  yield api.test(
      'file_allowlist-not-set',
      api.properties(
          **{
              '$chromeos/cros_test_plan_v2':
                  CrosTestPlanV2Properties(migration_configs=[
                      CrosTestPlanV2Properties.ProjectMigrationConfig(
                          host='chromium-review.googlesource.com',
                          project='src/projectA',
                          file_blocklist_regexps=['a/b/d/otherfile.json'],
                      ),
                  ])
          }), api.expect_exception('ValueError'),
      api.post_process(post_process.SummaryMarkdownRE,
                       '.*file_allowlist_regexps must be non-empty.*'),
      api.post_process(post_process.DropExpectation))
