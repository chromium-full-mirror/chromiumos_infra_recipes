# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_infra_config',
    'src_state',
    'test_util',
]

from google.protobuf import json_format
from recipe_engine import post_process

from PB.chromiumos import common
from PB.chromiumos.builder_config import BuilderConfig
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipes.chromeos.build_target import BuildTargetProperties
from PB.recipe_modules.chromeos.cros_infra_config.cros_infra_config import (
    CrosInfraConfigProperties)
from PB.recipe_modules.chromeos.cros_infra_config.examples.builder import (
    BuilderProperties)

PROPERTIES = BuilderProperties


def RunSteps(api, properties):
  target = properties.build_target
  commit = api.buildbucket.gitiles_commit
  changes = api.buildbucket.build.input.gerrit_changes

  api.assertions.assertFalse(api.cros_infra_config.is_configured)
  is_staging = None
  if properties.HasField('is_staging'):
    is_staging = properties.is_staging.value
  config = api.cros_infra_config.configure_builder(commit=commit,
                                                   changes=changes,
                                                   is_staging=is_staging)
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
  expect_host = p_commit.host or i_manifest.host
  expect_project = p_commit.project or i_manifest.project
  expect_id = (
      p_commit.id or
      '{}snapshot-HEAD-SHA'.format('staging-' if expected_is_staging else ''))
  expect_ref = (
      p_commit.ref or
      'refs/heads/{}snapshot'.format('staging-' if expected_is_staging else ''))
  expected_commit = common_pb2.GitilesCommit(host=expect_host,
                                             project=expect_project,
                                             id=expect_id, ref=expect_ref)
  if (config.general.manifest == BuilderConfig.General.PUBLIC and
      api.cros_infra_config.switch_to_external_manifest):
    expected_commit.host = api.src_state.external_manifest.host
    expected_commit.project = api.src_state.external_manifest.project

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

  def builder(build_target='amd64-generic', is_staging=None,
              expected_is_staging=False, expected_gitiles_commit=None,
              **kwargs):
    kwargs['exe'] = common_pb2.Executable(cipd_package='CIPD_PACKAGE',
                                          cipd_version='prod')
    build = api.test_util.test_child_build(build_target, **kwargs)
    props = BuilderProperties(
        builder=build.message.builder.builder,
        build_target=common.BuildTarget(name=build_target),
        expected_is_staging=expected_is_staging,
        expected_gitiles_commit=expected_gitiles_commit)
    if is_staging is not None:
      props.is_staging.value = is_staging
    # None of these example cases should fail, so verify that the build finished
    # successfully.
    return (build.build + api.properties(props) +
            api.post_check(post_process.StatusSuccess))

  # This has a commit and no changes.
  yield api.test('basic', builder())

  # This has (default) changes, and no commit.
  yield api.test('cq-build', builder(cq=True))

  # This has (default) changes, and our commit.
  yield api.test(
      'has_commit_and_changes',
      builder(cq=True, revision='993335c91267d304d44f712209139e8b84a87d8c'))

  # This has specified changes only, and no commit.
  yield api.test(
      'has_changes_and_no_commit',
      builder(revision=None,
              extra_changes=[common_pb2.GerritChange(change=1234)]))

  yield api.test('has_no_commit_and_no_changes', builder(revision=None))

  yield api.test(
      'follow_gitiles_commit_ref',
      builder(
          build_target='grunt', builder='grunt-postsubmit',
          git_ref='refs/heads/BRANCH',
          expected_gitiles_commit=common_pb2.GitilesCommit(
              host=i_manifest.host, project=i_manifest.project,
              ref='refs/heads/BRANCH', id='BRANCH-HEAD-SHA'),
          input_properties={
              '$chromeos/cros_infra_config': dict(honor_gitiles_commit_ref=True)
          }))

  yield api.test(
      'public_has_no_commit_and_no_changes',
      api.properties(
          **{
              '$chromeos/cros_infra_config':
                  CrosInfraConfigProperties(switch_to_external_manifest=True)
          }), builder(build_target='amd64-generic', revision=None))

  yield api.test(
      'branch_ref',
      builder(
          build_target='grunt', builder='grunt-postsubmit',
          git_repo=i_manifest.url, revision='5' * 40,
          git_ref='refs/heads/BRANCH',
          expected_gitiles_commit=common_pb2.GitilesCommit(
              host=i_manifest.host, project=i_manifest.project,
              ref='refs/heads/BRANCH', id='5' * 40)))

  yield api.test(
      'apply_gerrit_changes_false',
      builder(
          build_target='grunt', builder='grunt-postsubmit',
          git_repo=i_manifest.url, git_ref='refs/heads/snapshot',
          revision='5' * 40, expected_gitiles_commit=common_pb2.GitilesCommit(
              host=i_manifest.host, project=i_manifest.project,
              ref='refs/heads/snapshot', id='5' * 40),
          extra_changes=[common_pb2.GerritChange(change=1234)]))

  yield api.test(
      'has_parent',
      builder(tags=[
          {
              'key': 'parent_buildbucket_id',
              'value': 'parent_id'
          },
      ]))

  yield api.test('experiments', builder(experiments=['test-experiment']))

  yield api.test('missing_config',
                 builder(build_target='nosuch', builder='nosuch-cq'))

  yield api.test(
      'staging',
      builder(bucket='staging', builder='staging-amd64-generic-cq',
              expected_is_staging=True))

  yield api.test('forced-staging',
                 builder(is_staging=True, expected_is_staging=True))
