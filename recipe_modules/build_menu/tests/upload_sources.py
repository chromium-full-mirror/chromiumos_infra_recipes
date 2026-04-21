# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf.json_format import MessageToDict

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.go.chromium.org.luci.resultdb.proto.v1.common import GerritChange, GitilesCommit, Sources
from PB.recipe_modules.chromeos.build_menu.tests.test import TestProperties

from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'cros_infra_config',
    'build_menu',
    'cros_source',
    'src_state',
    'test_util',
]

PROPERTIES = TestProperties


external_git_repo = 'https://chromium.googlesource.com/chromiumos/manifest'
internal_git_repo = 'https://chrome-internal.googlesource.com/chromeos/manifest-internal'
git_ref = 'snapshot'
revision = 'c' * 40


def RunSteps(api, properties):
  api.cros_source.test_api.manifest_branch = properties.manifest_branch
  sources = api.build_menu.upload_sources(
      api.cros_infra_config.config) or Sources()
  api.assertions.assertEqual(sources, properties.expected_sources)


def GenTests(api):

  def test_build(build_target, number_of_gerrit_changes, input_properties=None):
    gerrit_changes = [
        common_pb2.GerritChange(host='chromium-review.googlesource.com',
                                project='chromiumos/infra', change=12340 + i,
                                patchset=1)
        for i in range(number_of_gerrit_changes)
    ]

    return api.test_util.test_child_build(
        build_target, cq=True, gerrit_changes=gerrit_changes,
        git_repo=internal_git_repo, git_ref=git_ref, revision=revision,
        input_properties=input_properties).build

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

  release_gitiles_commit = GitilesCommit(
      project='chromeos/manifest-internal-snapshot',
      host='chrome-internal.googlesource.com', commit_hash='ddd',
      ref='release-main-snapshot', position=33)
  expected_sources = Sources(gitiles_commit=release_gitiles_commit)

  input_properties = {
      '$chromeos/metadata': {
          'sources_gitiles_commit_override':
              MessageToDict(release_gitiles_commit)
      }
  }

  yield api.test(
      'release-branch',
      api.test_util.test_child_build('kukui',
                                     builder_name='kukui-release-R111-12345.B',
                                     input_properties=input_properties,
                                     git_repo=internal_git_repo,
                                     git_ref='release-R111-12345.B',
                                     revision=revision).build,
      api.properties(
          TestProperties(expected_sources=expected_sources,
                         manifest_branch='release-R111-12345.B')),
      api.post_check(post_process.MustRun, 'upload sources metadata'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'release-no-commit',
      api.test_util.test_child_build(
          'kukui', builder_name='kukui-release-R111-12345.B').build,
      api.properties(TestProperties(manifest_branch='release-R111-12345.B')),
      api.post_check(post_process.DoesNotRun, 'upload sources metadata'),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'factory',
      api.test_util.test_child_build(
          'factory-corsola-15197.B-corsola',
          builder_name='staging-factory-corsola-15197.B-corsola').build,
      api.cros_infra_config.override_builder_configs_test_data(
          api.cros_infra_config.builder_configs_test_data, ref='HEAD'),
      api.post_check(post_process.DoesNotRun, 'upload sources metadata'),
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

  # Use annealing commit on ToT.
  expected_sources = Sources(gitiles_commit=gitiles_commit)
  yield api.test(
      'release-tot',
      api.test_util.test_child_build('kukui', builder_name='kukui-release-main',
                                     git_repo=internal_git_repo,
                                     git_ref=git_ref, revision=revision).build,
      api.properties(TestProperties(expected_sources=expected_sources)),
      api.post_check(post_process.MustRun, 'upload sources metadata'),
      api.post_process(post_process.DropExpectation),
  )

  gitiles_commit = GitilesCommit(project='chromiumos/manifest',
                                 host='chromium.googlesource.com',
                                 commit_hash=revision, ref=git_ref,
                                 position=999)
  expected_sources = Sources(gitiles_commit=gitiles_commit)
  yield api.test(
      'public-target-no-override',
      api.test_util.test_child_build('amd64-generic',
                                     git_repo=external_git_repo,
                                     revision=revision, git_ref=git_ref).build,
      api.properties(TestProperties(expected_sources=expected_sources)),
      api.post_process(post_process.DropExpectation),
  )

  gitiles_commit = GitilesCommit(project='chromeos/test',
                                 host='test.googlesource.com',
                                 commit_hash='testtest', ref='test',
                                 position=123)
  expected_sources = Sources(gitiles_commit=gitiles_commit,
                             changelists=gerrit_changes)
  input_properties = {
      '$chromeos/metadata': {
          'sources_gitiles_commit_override': MessageToDict(gitiles_commit)
      }
  }
  yield api.test(
      'gitiles-commit-passed-in',
      test_build('staging-atlas', number_of_gerrit_changes=10,
                 input_properties=input_properties),
      api.properties(TestProperties(expected_sources=expected_sources)),
      api.post_process(post_process.DropExpectation),
  )
