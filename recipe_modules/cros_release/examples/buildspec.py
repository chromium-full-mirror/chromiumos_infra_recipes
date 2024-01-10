# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from recipe_engine import post_process

from PB.recipe_modules.chromeos.cros_release.examples.buildspec import BuildspecProperties
from PB.recipe_modules.chromeos.cros_source.cros_source import ManifestLocation

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'build_reporting',
    'cros_release',
    'cros_source',
    'git',
    'orch_menu',
    'test_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = BuildspecProperties


def RunSteps(api, properties):
  if properties.manifest_branch:
    api.cros_source.test_api.manifest_branch = properties.manifest_branch

  api.assertions.assertEqual(api.cros_release.uprev_packages(),
                             not properties.expect_uprev_packages_failure)

  api.cros_release.create_buildspec()
  api.assertions.assertIsNotNone(api.cros_release.buildspec)

  api.cros_release.create_buildspec(gs_location='bucket/foo/')
  api.assertions.assertIsNotNone(api.cros_release.buildspec)

  api.cros_release.create_buildspec(gs_location='gs://bucket/foo/')
  api.assertions.assertIsNotNone(api.cros_release.buildspec)

  api.cros_release.create_buildspec(gs_location='bucket/foo/bar.xml')
  api.assertions.assertIsNotNone(api.cros_release.buildspec)

  api.cros_release.buildspec = ManifestLocation(manifest_gs_path='foo')
  api.assertions.assertEqual(api.cros_release.buildspec.manifest_gs_path, 'foo')


def GenTests(api):
  yield api.orch_menu.test(
      'basic', api.git.diff_check(True),
      api.post_check(post_process.LogEquals, 'push uprevs', 'Passed Uprevs',
                     ('src/overlay\nsrc/private-overlay')),
      api.post_check(
          post_process.MustRun,
          'create buildspec.commit buildspec.commit buildspecs/99/1234.56.0.xml to main'
      ),
      api.post_check(post_process.DoesNotRun,
                     'create buildspec.commit buildspec as snapshot'),
      builder='release-main-orchestrator')

  yield api.orch_menu.test(
      'uprev-fail',
      api.properties(
          BuildspecProperties(
              expect_uprev_packages_failure=True,
          ),
      ), api.git.diff_check(True),
      api.step_data(
          ('push uprevs.push to src/private-overlay.git push src/private-overlay'
          ),
          retcode=1,
      ),
      api.post_check(post_process.LogEquals, 'push uprevs', 'Passed Uprevs',
                     ('src/overlay')),
      api.post_check(post_process.LogEquals, 'push uprevs', 'Failed Uprevs',
                     ('src/private-overlay')),
      api.post_check(
          post_process.MustRun,
          'create buildspec.commit buildspec.commit buildspecs/99/1234.56.0.xml to main'
      ),
      api.post_check(post_process.DoesNotRun,
                     'create buildspec.commit buildspec as snapshot'),
      builder='release-main-orchestrator')

  yield api.orch_menu.test(
      'staging-build', api.git.diff_check(True),
      api.post_check(
          post_process.MustRun,
          'create buildspec.commit buildspec.commit buildspecs/99/1234.56.0-8945511751514863184.xml to release'
      ),
      api.post_check(post_process.DoesNotRun,
                     'create buildspec.commit buildspec as snapshot'),
      builder='staging-release-main-orchestrator')

  yield api.orch_menu.test(
      'staging-build-no-diff', api.git.diff_check(False),
      api.post_check(
          post_process.DoesNotRun,
          'create buildspec.commit buildspec.commit buildspecs/99/1234.56.0.xml to release'
      ),
      api.post_check(post_process.StepTextEquals,
                     'create buildspec.commit buildspec',
                     'no change since last commit'),
      api.post_check(post_process.DoesNotRun,
                     'create buildspec.commit buildspec as snapshot'),
      builder='staging-release-main-orchestrator')

  yield api.orch_menu.test(
      'commit-as-snapshot-tot',
      api.properties(**{
          '$chromeos/cros_release': {
              'commit_buildspec_as_snapshot': True,
          },
      }), api.git.diff_check(True),
      api.post_check(
          post_process.MustRun,
          'create buildspec.commit buildspec as snapshot.commit to main-release-snapshot'
      ),
      api.post_check(
          post_process.LogContains,
          'create buildspec.commit buildspec as snapshot.commit to main-release-snapshot.write commit message',
          'commit_msg_tmp_4',
          ['Cr-Commit-Position: refs/heads/main-release-snapshot@{#1}']),
      builder='release-main-orchestrator')

  yield api.orch_menu.test(
      'commit-as-snapshot-tot-snapshot',
      api.properties(
          **{
              '$chromeos/cros_release': {
                  'commit_buildspec_as_snapshot': True,
              },
              'manifest_branch': 'snapshot',
          }), api.git.diff_check(True),
      api.override_step_data(
          'create buildspec.commit buildspec as snapshot.read git footers',
          stdout=api.raw_io.output('refs/heads/main-release-snapshot')),
      api.post_check(
          post_process.MustRun,
          'create buildspec.commit buildspec as snapshot.commit to main-release-snapshot'
      ),
      api.post_check(
          post_process.LogContains,
          'create buildspec.commit buildspec as snapshot.commit to main-release-snapshot.write commit message',
          'commit_msg_tmp_4',
          ['Cr-Commit-Position: refs/heads/main-release-snapshot@{#102}']),
      builder='release-main-orchestrator')

  yield api.orch_menu.test(
      'commit-as-snapshot-branch',
      api.properties(
          **{
              '$chromeos/cros_release': {
                  'commit_buildspec_as_snapshot': True,
              },
              'manifest_branch': 'release-R108-15183.B',
          }),
      api.git.diff_check(True),
      # We must not have just branched, the previous commit was for the same branch.
      # Counter does not reset.
      api.override_step_data(
          'create buildspec.commit buildspec as snapshot.read git footers',
          stdout=api.raw_io.output('refs/heads/release-R108-15183.B-snapshot')),
      # Previous commit has a Cr-Branched-From footer, that should be recycled.
      api.override_step_data(
          'create buildspec.commit buildspec as snapshot.read git footers (3)',
          stdout=api.raw_io.output(
              '12345abcde-refs/heads/main-release-snapshot@{#65}')),
      api.post_check(
          post_process.MustRun,
          'create buildspec.commit buildspec as snapshot.commit to release-R108-15183.B-snapshot'
      ),
      api.post_check(
          post_process.LogContains,
          'create buildspec.commit buildspec as snapshot.commit to release-R108-15183.B-snapshot.write commit message',
          'commit_msg_tmp_4', [
              'Cr-Commit-Position: refs/heads/release-R108-15183.B-snapshot@{#102}',
              'Cr-Branched-From: 12345abcde-refs/heads/main-release-snapshot@{#65}',
          ]),
      builder='release-R108-15183.B-orchestrator')

  yield api.orch_menu.test(
      'commit-as-snapshot-branch-newly-branched',
      api.properties(
          **{
              '$chromeos/cros_release': {
                  'commit_buildspec_as_snapshot': True,
              },
              'manifest_branch': 'release-R108-15183.B',
          }),
      api.git.diff_check(True),
      # We must have just branched, the previous commit was for main-release-snapshot.
      # Counter should reset to 1.
      api.override_step_data(
          'create buildspec.commit buildspec as snapshot.read git footers',
          stdout=api.raw_io.output('refs/heads/main-release-snapshot')),
      api.post_check(
          post_process.MustRun,
          'create buildspec.commit buildspec as snapshot.commit to release-R108-15183.B-snapshot'
      ),
      api.post_check(
          post_process.LogContains,
          'create buildspec.commit buildspec as snapshot.commit to release-R108-15183.B-snapshot.write commit message',
          'commit_msg_tmp_4', [
              'Cr-Commit-Position: refs/heads/release-R108-15183.B-snapshot@{#1}',
              'Cr-Branched-From: deadbeefdeadbeefdeadbeefdeadbeefdeadbeef-refs/heads/main-release-snapshot@{#101}',
          ]),
      builder='release-R108-15183.B-orchestrator')

  yield api.orch_menu.test(
      'commit-as-snapshot-staging',
      api.properties(**{
          '$chromeos/cros_release': {
              'commit_buildspec_as_snapshot': True,
          },
      }), api.git.diff_check(True),
      api.post_check(
          post_process.MustRun,
          'create buildspec.commit buildspec as snapshot.commit to staging-buildspec-snapshot'
      ), builder='staging-release-main-orchestrator')

  yield api.orch_menu.test(
      'commit-as-snapshot-exception',
      api.properties(**{
          '$chromeos/cros_release': {
              'commit_buildspec_as_snapshot': True,
          },
      }), api.git.diff_check(True),
      api.step_data(
          'create buildspec.commit buildspec as snapshot.clone manifest-internal.git clone',
          retcode=1),
      api.post_check(post_process.StepException,
                     'create buildspec.commit buildspec as snapshot'),
      api.post_process(post_process.DropExpectation),
      builder='staging-release-main-orchestrator')
