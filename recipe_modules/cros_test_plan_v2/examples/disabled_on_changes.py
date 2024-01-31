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
        project='src/projectB',
        change=456,
        patchset=7,
    ),
]


def RunSteps(api):
  api.assertions.assertFalse(
      api.cros_test_plan_v2.enabled_on_changes(gerrit_changes))


def GenTests(api):

  yield api.test(
      'file_not_in_allowlist',
      api.properties(
          **{
              '$chromeos/cros_test_plan_v2':
                  CrosTestPlanV2Properties(migration_configs=[
                      CrosTestPlanV2Properties.ProjectMigrationConfig(
                          host='chromium-review.googlesource.com',
                          project='src/projectA',
                          file_allowlist_regexps=['a/b/.*'],
                          branch_allowlist_regexps=['.*'],
                      ),
                      CrosTestPlanV2Properties.ProjectMigrationConfig(
                          host='chromium-review.googlesource.com',
                          project='src/projectB',
                          file_allowlist_regexps=['test.json'],
                          branch_allowlist_regexps=['.*'],
                      )
                  ])
          }),
      api.gerrit.set_gerrit_fetch_changes_response(
          'check test planning v2 enabled',
          gerrit_changes,
          {
              123: {
                  'files': {
                      'a/b/d/test.txt': {},
                      'a/otherdir/test2.txt': {}
                  }
              },
          },
          iteration=1,
      ),
      api.post_process(
          post_process.StepTextEquals, 'check test planning v2 enabled',
          ('path "a/otherdir/test2.txt" not in allow list, not enabling test planning v2'
          )),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'file_in_blocklist',
      api.properties(
          **{
              '$chromeos/cros_test_plan_v2':
                  CrosTestPlanV2Properties(migration_configs=[
                      CrosTestPlanV2Properties.ProjectMigrationConfig(
                          host='chromium-review.googlesource.com',
                          project='src/projectA',
                          branch_allowlist_regexps=['.*'],
                          file_allowlist_regexps=['a/b/.*'],
                          file_blocklist_regexps=['a/b/d/otherfile.*'],
                      ),
                      CrosTestPlanV2Properties.ProjectMigrationConfig(
                          host='chromium-review.googlesource.com',
                          project='src/projectB',
                          branch_allowlist_regexps=['.*'],
                          file_allowlist_regexps=['test.json'],
                      )
                  ])
          }),
      api.gerrit.set_gerrit_fetch_changes_response(
          'check test planning v2 enabled', gerrit_changes, {
              123: {
                  'files': {
                      'a/b/d/test.txt': {},
                      'a/b/d/otherfile.txt': {}
                  }
              },
          }, iteration=1),
      api.post_process(
          post_process.StepTextEquals, 'check test planning v2 enabled',
          ('path "a/b/d/otherfile.txt" in block list, not enabling test planning v2'
          )),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'branch_not_in_allowlist',
      api.properties(
          **{
              '$chromeos/cros_test_plan_v2':
                  CrosTestPlanV2Properties(migration_configs=[
                      CrosTestPlanV2Properties.ProjectMigrationConfig(
                          host='chromium-review.googlesource.com',
                          project='src/projectA',
                          branch_allowlist_regexps=['.*factory.*'],
                          file_allowlist_regexps=['a/b/.*'],
                      ),
                      CrosTestPlanV2Properties.ProjectMigrationConfig(
                          host='chromium-review.googlesource.com',
                          project='src/projectB',
                          file_allowlist_regexps=['.*'],
                      ),
                  ])
          }),
      api.gerrit.set_gerrit_fetch_changes_response(
          'check test planning v2 enabled', gerrit_changes, {
              123: {
                  'files': {
                      'a/b/d/test.txt': {},
                      'a/b/d/otherfile.txt': {}
                  },
                  'branch': 'release-R123',
              },
          }, iteration=1),
      api.post_process(
          post_process.StepTextEquals, 'check test planning v2 enabled',
          ('branch "release-R123" not in allow list, not enabling test planning v2'
          )),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'no_migration_config',
      api.properties(
          **{
              '$chromeos/cros_test_plan_v2':
                  CrosTestPlanV2Properties(migration_configs=[
                      CrosTestPlanV2Properties.ProjectMigrationConfig(
                          host='chromium-review.googlesource.com',
                          project='src/otherproject',
                          file_allowlist_regexps=['a/b/.*'],
                          file_blocklist_regexps=['a/b/d/otherfile.*'],
                      ),
                  ])
          }),
      api.post_process(
          post_process.StepTextEquals, 'check test planning v2 enabled',
          ('no migration config found for (chromium-review.googlesource.com, '
           'src/projectA), not enabling test planning v2')),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'project_in_blocklist',
      api.properties(
          **{
              '$chromeos/cros_test_plan_v2':
                  CrosTestPlanV2Properties(migration_configs=[
                      CrosTestPlanV2Properties.ProjectMigrationConfig(
                          host='chromium-review.googlesource.com',
                          project='.*',
                          project_blocklist=['src/project[A|C]'],
                          file_allowlist_regexps=['.*'],
                          branch_allowlist_regexps=['.*'],
                      ),
                  ]),
          },
      ),
      api.post_process(
          post_process.StepTextEquals, 'check test planning v2 enabled',
          ('project src/projectA is blocklisted, not enabling test planning v2'
          )),
      api.post_process(post_process.DropExpectation),
  )
