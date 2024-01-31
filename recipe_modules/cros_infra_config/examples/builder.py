# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.chromiumos import common
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.cros_infra_config.examples.builder import BuilderProperties
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_infra_config',
    'src_state',
    'test_util',
]


PROPERTIES = BuilderProperties


def RunSteps(api, properties):
  target = properties.build_target
  commit = api.buildbucket.gitiles_commit
  changes = api.buildbucket.build.input.gerrit_changes

  api.assertions.assertFalse(api.cros_infra_config.is_configured)
  config = api.cros_infra_config.configure_builder(
      commit=commit, changes=changes,
      choose_branch=not properties.no_choose_branch)
  api.assertions.assertTrue(api.cros_infra_config.is_configured)
  api.assertions.assertEqual(config, api.cros_infra_config.config)

  builder = config.id.name if config else 'nosuch-cq'
  api.assertions.assertEqual(properties.builder, builder)
  if not config:
    api.assertions.assertIsNotNone(api.cros_infra_config.config_or_default)
    return

  expected_is_staging = properties.expected_is_staging
  p_commit = properties.expected_gitiles_commit
  i_manifest = api.src_state.internal_manifest

  expected_commit = common_pb2.GitilesCommit()
  if not properties.expect_empty_gitiles_commit:
    expect_host = p_commit.host or i_manifest.host
    expect_project = p_commit.project or i_manifest.project
    if properties.no_choose_branch:
      expect_id = ''
      expect_ref = ''
    else:
      expect_id = (
          p_commit.id or '{}snapshot-HEAD-SHA'.format(
              'staging-' if expected_is_staging else ''))
      expect_ref = (
          p_commit.ref or 'refs/heads/{}snapshot'.format(
              'staging-' if expected_is_staging else ''))
    expected_commit = common_pb2.GitilesCommit(host=expect_host,
                                               project=expect_project,
                                               id=expect_id, ref=expect_ref)

  api.assertions.assertEqual(expected_commit,
                             api.cros_infra_config.gitiles_commit)
  want = [] if not (changes and config.build.apply_gerrit_changes) else changes
  api.assertions.assertEqual(want, api.cros_infra_config.gerrit_changes)
  api.assertions.assertEqual(api.cros_infra_config.is_staging,
                             expected_is_staging)

  # Force a reload of the config.
  api.assertions.assertEqual(config, api.cros_infra_config.fresh_config)

  api.assertions.assertEqual(target.name,
                             api.cros_infra_config.get_build_target_name())

  api.assertions.assertEqual(
      target.name,
      api.cros_infra_config.get_build_target_name(api.buildbucket.build))

  api.assertions.assertEqual({target.name: api.buildbucket.build},
                             api.cros_infra_config.build_target_dict(
                                 [api.buildbucket.build]))


def GenTests(api):

  i_manifest = api.src_state.internal_manifest
  e_manifest = api.src_state.external_manifest

  def builder(build_target='grunt', expected_is_staging=False,
              expected_gitiles_commit=None, expect_empty_gitiles_commit=False,
              choose_branch=True, **kwargs):
    kwargs['exe'] = common_pb2.Executable(cipd_package='CIPD_PACKAGE',
                                          cipd_version='prod')
    build = api.test_util.test_child_build(build_target, **kwargs)
    props = BuilderProperties(
        builder=build.message.builder.builder,
        build_target=common.BuildTarget(name=build_target),
        expected_is_staging=expected_is_staging,
        expected_gitiles_commit=expected_gitiles_commit,
        expect_empty_gitiles_commit=expect_empty_gitiles_commit,
        no_choose_branch=not choose_branch)
    # None of these example cases should fail, so verify that the build finished
    # successfully.  We will inherit the name from the other call to api.test.
    return api.test(
        None,
        build.build,
        api.properties(props),
    )

  # This has a commit and no changes.
  yield api.test('basic', builder())

  # This has (default) changes, and no commit.
  yield api.test('cq-build', builder(build_target='coral', cq=True))

  # This has (default) changes, and our commit.
  yield api.test(
      'has-commit-and-changes',
      builder(build_target='coral', cq=True,
              revision='993335c91267d304d44f712209139e8b84a87d8c'))

  # This has specified changes only, and no commit.
  yield api.test(
      'has-changes-and-no-commit',
      builder(revision=None,
              extra_changes=[common_pb2.GerritChange(change=1234)]))

  yield api.test('has_no_commit_and_no_changes', builder(revision=None))

  yield api.test(
      'follow-gitiles-commit-ref',
      builder(
          build_target='grunt', builder='grunt-postsubmit',
          git_ref='refs/heads/BRANCH',
          expected_gitiles_commit=common_pb2.GitilesCommit(
              host=i_manifest.host, project=i_manifest.project,
              ref='refs/heads/BRANCH', id='BRANCH-HEAD-SHA'), input_properties={
                  '$chromeos/cros_infra_config': {
                      'honor_gitiles_commit_ref': True
                  }
              }))

  yield api.test(
      'fixes-manifest-project',
      builder(
          build_target='grunt', builder='grunt-postsubmit', choose_branch=False,
          git_repo='https://chromium.googlesource.com/chromium/src',
          git_ref='refs/tags/93.0.4552.0',
          expected_gitiles_commit=common_pb2.GitilesCommit(
              host=i_manifest.host, project=i_manifest.project, ref='',
              id=''), input_properties={
                  '$chromeos/cros_infra_config': {
                      'honor_gitiles_commit_ref': True
                  }
              }))

  yield api.test(
      'fixes-manifest-project-choose-branch',
      builder(
          build_target='grunt', builder='grunt-postsubmit', choose_branch=True,
          git_repo='https://chromium.googlesource.com/chromium/src',
          git_ref='refs/tags/93.0.4552.0',
          expected_gitiles_commit=common_pb2.GitilesCommit(
              host=i_manifest.host, project=i_manifest.project,
              ref='refs/heads/snapshot',
              id='snapshot-HEAD-SHA'), input_properties={
                  '$chromeos/cros_infra_config': {
                      'honor_gitiles_commit_ref': True
                  }
              }))

  yield api.test(
      'follow-gitiles-commit-ref-main',
      builder(
          build_target='grunt', builder='grunt-postsubmit',
          git_ref='refs/heads/main',
          expected_gitiles_commit=common_pb2.GitilesCommit(
              host=i_manifest.host, project=i_manifest.project,
              ref=i_manifest.ref,
              id='%s-HEAD-SHA' % i_manifest.branch), input_properties={
                  '$chromeos/cros_infra_config': {
                      'honor_gitiles_commit_ref': True
                  }
              }))

  yield api.test(
      'public-has-no-commit-and-no-changes',
      builder(
          build_target='amd64-generic', revision=None,
          expected_gitiles_commit=common_pb2.GitilesCommit(
              host=e_manifest.host,
              project=e_manifest.project,
          )))

  yield api.test(
      'branch-ref',
      builder(
          build_target='grunt', builder='grunt-postsubmit',
          git_repo=i_manifest.url, revision='5' * 40,
          git_ref='refs/heads/BRANCH',
          expected_gitiles_commit=common_pb2.GitilesCommit(
              host=i_manifest.host, project=i_manifest.project,
              ref='refs/heads/BRANCH', id='5' * 40)))

  yield api.test(
      'apply-gerrit-changes-false',
      builder(
          build_target='grunt', builder='grunt-postsubmit',
          git_repo=i_manifest.url, git_ref='refs/heads/snapshot',
          revision='5' * 40, expected_gitiles_commit=common_pb2.GitilesCommit(
              host=i_manifest.host, project=i_manifest.project,
              ref='refs/heads/snapshot', id='5' * 40),
          extra_changes=[common_pb2.GerritChange(change=1234)]))

  yield api.test(
      'apply-gerrit-changes-false-no-choose-branch',
      builder(build_target='grunt', builder='grunt-postsubmit',
              choose_branch=False,
              extra_changes=[common_pb2.GerritChange(change=1234)], cq=True,
              expect_empty_gitiles_commit=False),
      api.post_check(post_process.MustRun,
                     'configure builder.update src_state.gitiles_commit'))

  yield api.test(
      'has-parent',
      builder(tags=[
          {
              'key': 'parent_buildbucket_id',
              'value': 'parent_id'
          },
      ]))

  yield api.test('experiments', builder(experiments=['test-experiment']))

  yield api.test('missing-config',
                 builder(build_target='nosuch', builder='nosuch-cq'))

  yield api.test(
      'staging',
      builder(
          bucket='staging', builder='staging-amd64-generic-cq',
          expected_is_staging=True,
          expected_gitiles_commit=common_pb2.GitilesCommit(
              host=e_manifest.host,
              project=e_manifest.project,
          )))
