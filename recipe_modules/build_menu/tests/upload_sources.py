# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.resultdb.proto.v1.common import GerritChange, GitilesCommit
from PB.go.chromium.org.luci.resultdb.proto.v1.invocation import Sources
from PB.recipe_modules.chromeos.build_menu.tests.test import TestProperties

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_infra_config',
    'build_menu',
    'src_state',
    'test_util',
]

PROPERTIES = TestProperties

PYTHON_VERSION_COMPATIBILITY = 'PY3'

external_git_repo = 'https://chromium.googlesource.com/chromiumos/manifest'
internal_git_repo = 'https://chrome-internal.googlesource.com/chromeos/manifest-internal'
git_ref = 'snapshot'
revision = 'c' * 40


def RunSteps(api, properties):
  sources = api.build_menu.upload_sources(
      api.cros_infra_config.config) or Sources()
  api.assertions.assertEqual(sources, properties.expected_sources)


def GenTests(api):

  def test_build(build_target, number_of_gerrit_changes):
    gerrit_changes = [
        common_pb2.GerritChange(host='chromium-review.googlesource.com',
                                project='chromiumos/infra', change=12340 + i,
                                patchset=1)
        for i in range(number_of_gerrit_changes)
    ]

    experiments = ['chromeos.build_menu.upload_sources']
    return api.test_util.test_child_build(build_target, cq=True,
                                          gerrit_changes=gerrit_changes,
                                          git_repo=internal_git_repo,
                                          git_ref=git_ref, revision=revision,
                                          experiments=experiments).build

  yield api.test(
      'no-artifacts-bucket',
      api.test_util.test_child_build('chromite', cq=True).build,
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'exp-not-enabled',
      api.test_util.test_child_build('atlas', cq=True).build,
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'public-target',
      api.test_util.test_child_build(
          'staging-amd64-generic', cq=True, git_repo=external_git_repo,
          revision=revision, git_ref=git_ref,
          experiments=['chromeos.build_menu.upload_sources']).build,
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'staging-release',
      api.test_util.test_child_build(
          'staging-eve', builder_name='staging-eve-release-main',
          experiments=['chromeos.build_menu.upload_sources']).build,
      api.post_process(post_process.DropExpectation),
  )

  gitiles_commit = GitilesCommit(project='chromeos/manifest-internal',
                                 host='chrome-internal.googlesource.com',
                                 commit_hash=revision, ref=git_ref,
                                 position=999)
  gerrit_changes = [
      GerritChange(host='chromium-review.googlesource.com',
                   project='chromiumos/infra', change=12340 + i, patchset=1)
      for i in range(10)
  ]
  expected_sources = Sources(gitiles_commit=gitiles_commit,
                             changelists=gerrit_changes)
  yield api.test(
      'basic',
      test_build('staging-atlas', number_of_gerrit_changes=10),
      api.properties(TestProperties(expected_sources=expected_sources)),
  )

  yield api.test(
      'ignored-exception',
      test_build('staging-atlas', number_of_gerrit_changes=10),
      api.step_data('upload sources metadata.gsutil upload', retcode=1),
      api.post_process(post_process.DropExpectation),
  )

  expected_sources.is_dirty = True
  yield api.test(
      'more-than-ten-changes',
      test_build('staging-atlas', number_of_gerrit_changes=11),
      api.properties(TestProperties(expected_sources=expected_sources)),
  )
