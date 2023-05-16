# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from recipe_engine import post_process

from PB.recipe_modules.chromeos.cros_release.examples.buildspec import BuildspecProperties
from PB.recipe_modules.chromeos.cros_source.cros_source import ManifestLocation

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
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
      api.post_check(
          post_process.MustRun,
          'create buildspec.commit buildspec.commit buildspecs/99/1234.56.0.xml to master'
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
      ), builder='release-main-orchestrator')

  yield api.orch_menu.test(
      'commit-as-snapshot-tot-snapshot',
      api.properties(
          **{
              '$chromeos/cros_release': {
                  'commit_buildspec_as_snapshot': True,
              },
              'manifest_branch': 'snapshot',
          }), api.git.diff_check(True),
      api.post_check(
          post_process.MustRun,
          'create buildspec.commit buildspec as snapshot.commit to main-release-snapshot'
      ), builder='release-main-orchestrator')

  yield api.orch_menu.test(
      'commit-as-snapshot-branch',
      api.properties(
          **{
              '$chromeos/cros_release': {
                  'commit_buildspec_as_snapshot': True,
              },
              'manifest_branch': 'release-R108-15183.B',
          }), api.git.diff_check(True),
      api.post_check(
          post_process.MustRun,
          'create buildspec.commit buildspec as snapshot.commit to release-R108-15183.B-snapshot'
      ), builder='release-R108-15183.B-orchestrator')

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
