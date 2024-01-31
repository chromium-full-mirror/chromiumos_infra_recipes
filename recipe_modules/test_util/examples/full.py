# -*- coding: utf-8 -*-
# Copyright 2020 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf.json_format import ParseDict

from PB.chromiumos.common import BuildTarget
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.build_menu.build_menu import BuildMenuProperties
from PB.recipe_modules.chromeos.test_util.examples.full import TestProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'cros_tags',
    'test_util',
]


PROPERTIES = TestProperties


def RunSteps(api, properties):
  build = api.buildbucket.build
  api.assertions.assertEqual(build.builder.project, properties.expected_project)
  api.assertions.assertEqual(build.builder.bucket, properties.expected_bucket)
  api.assertions.assertEqual(build.builder.builder, properties.expected_builder)

  props = ParseDict(build.input.properties, BuildMenuProperties(),
                    ignore_unknown_fields=True)
  api.assertions.assertEqual(properties.expected_build_target,
                             props.build_target.name)
  api.assertions.assertEqual(properties.expected_force_relevant_build,
                             props.force_relevant_build, False)

  # Check host for "True"-ness to see if it is set.  We do not care what the
  # value is for the purposes of testing, since we do not want to hard code the
  # answer that buildbucket defaults to.
  api.assertions.assertEqual(properties.expect_commit,
                             api.buildbucket.gitiles_commit.host != '')

  api.assertions.assertEqual(
      len(build.input.gerrit_changes), properties.expected_cl_count)

  if properties.expected_create_time:
    api.assertions.assertEqual(properties.expected_create_time,
                               build.create_time.seconds)
  else:
    # Buildbucket has a default for create time.
    api.assertions.assertNotEqual(0, build.create_time.seconds)
  api.assertions.assertEqual(properties.expected_start_time,
                             build.start_time.seconds)
  api.assertions.assertEqual(properties.expected_update_time,
                             build.update_time.seconds)
  api.assertions.assertEqual(properties.expected_end_time,
                             build.end_time.seconds)

  if properties.expected_executable:
    api.assertions.assertEqual(api.buildbucket.build.exe,
                               properties.expected_executable)

  props = ParseDict(build.output.properties, BuildMenuProperties(),
                    ignore_unknown_fields=True)
  if properties.expected_output_build_target_name:
    api.assertions.assertEqual(properties.expected_output_build_target_name,
                               props.build_target.name)


def GenTests(api):

  yield api.test(
      'postsubmit-child',
      api.test_util.test_child_build('amd64-generic').build,
      api.properties(
          TestProperties(expected_project='chromeos',
                         expected_bucket='postsubmit',
                         expected_builder='amd64-generic-postsubmit',
                         expected_build_target='amd64-generic',
                         expect_commit=True)))

  yield api.test(
      'with-build_target',
      api.test_util.test_child_build('myboard').build,
      api.properties(
          TestProperties(expected_project='chromeos',
                         expected_bucket='postsubmit',
                         expected_builder='myboard-postsubmit',
                         expect_commit=True, expected_build_target='myboard')))

  yield api.test(
      'child-with-properties-message',
      api.test_util.test_child_build(
          'amd64-generic', input_properties=BuildMenuProperties(
              force_relevant_build=True)).build,
      api.properties(
          TestProperties(expected_project='chromeos',
                         expected_bucket='postsubmit',
                         expected_builder='amd64-generic-postsubmit',
                         expected_build_target='amd64-generic',
                         expect_commit=True,
                         expected_force_relevant_build=True)))

  yield api.test(
      'child-with-properties-dict',
      api.test_util.test_child_build(
          'amd64-generic', input_properties={
              'force_relevant_build': True
          }).build,
      api.properties(
          TestProperties(expected_project='chromeos',
                         expected_bucket='postsubmit',
                         expected_builder='amd64-generic-postsubmit',
                         expected_build_target='amd64-generic',
                         expect_commit=True,
                         expected_force_relevant_build=True)))

  yield api.test(
      'with-properties-message',
      api.test_util.test_build(
          builder='amd64-generic-postsubmit',
          input_properties=BuildMenuProperties(
              build_target=BuildTarget(name='amd64-generic'))).build,
      api.properties(
          TestProperties(expected_project='chromeos',
                         expected_bucket='postsubmit',
                         expected_builder='amd64-generic-postsubmit',
                         expected_build_target='amd64-generic',
                         expect_commit=True)))

  yield api.test(
      'with-properties-dict',
      api.test_util.test_build(
          builder='amd64-generic-postsubmit', input_properties={
              'build_target': {
                  'name': 'amd64-generic'
              }
          }).build,
      api.properties(
          TestProperties(expected_project='chromeos',
                         expected_bucket='postsubmit',
                         expected_builder='amd64-generic-postsubmit',
                         expected_build_target='amd64-generic',
                         expect_commit=True)))

  props = api.test_util.build_menu_properties(build_target_name='myboard')
  yield api.test(
      'with-properties-dict-from-build-target-properties',
      api.test_util.test_child_build('myboard', input_properties=props,
                                     builder='amd64-generic-postsubmit').build,
      api.properties(
          TestProperties(expected_project='chromeos',
                         expected_bucket='postsubmit',
                         expected_builder='amd64-generic-postsubmit',
                         expect_commit=True, expected_build_target='myboard')))

  # Also verify that project and bucket are handled correctly.
  yield api.test(
      'cq-build',
      api.test_util.test_child_build('amd64-generic', cq=True,
                                     project='myproject',
                                     bucket='bucket').build,
      api.properties(
          TestProperties(expected_project='myproject', expected_bucket='bucket',
                         expected_builder='amd64-generic-bucket',
                         expected_build_target='amd64-generic',
                         expected_cl_count=1)))

  # Also verify that builder is handled correctly, and that None yields no
  # build_target.
  yield api.test(
      'cq-build-multiple-changes',
      api.test_util.test_child_build(
          'amd64-generic', cq=True, builder='my-builder',
          extra_changes=[common_pb2.GerritChange(change=5555)]).build,
      api.properties(
          TestProperties(expected_project='chromeos', expected_bucket='cq',
                         expected_builder='my-builder',
                         expected_build_target='amd64-generic',
                         expected_cl_count=2)))

  # If we want a specific commit on a specific branch, and specific CLs, this is
  # how.
  yield api.test(
      'specific-commit-and-changes',
      api.test_util.test_orchestrator(
          bucket='cq',
          extra_changes=[
              common_pb2.GerritChange(change=5555),
              common_pb2.GerritChange(change=8888),
              common_pb2.GerritChange(change=9999)
          ],
          git_ref='refs/heads/mybranch',
          revision='deadbeefdeadbeef',
          output_gitiles_commit=common_pb2.GitilesCommit(
              id='deadbeefdeadbeef',
              ref='refs/heads/mybranch',
          ),
      ).build,
      api.properties(
          TestProperties(expected_project='chromeos', expected_bucket='cq',
                         expected_builder='cq-orchestrator', expect_commit=True,
                         expected_build_target='', expected_cl_count=3)))

  yield api.test(
      'no-commit-and-no-changes',
      api.test_util.test_child_build(
          'amd64-generic', revision=None,
          tags=api.cros_tags.tags(my_tag='foo')).build,
      api.properties(
          TestProperties(expected_project='chromeos',
                         expected_bucket='postsubmit',
                         expected_builder='amd64-generic-postsubmit',
                         expected_build_target='amd64-generic')))

  yield api.test(
      'with-times',
      api.test_util.test_child_build('amd64-generic', create_time=1,
                                     start_time=2, update_time=3,
                                     end_time=4).build,
      api.properties(
          TestProperties(
              expected_project='chromeos',
              expected_bucket='postsubmit',
              expected_builder='amd64-generic-postsubmit',
              expected_build_target='amd64-generic',
              expect_commit=True,
              expected_create_time=1,
              expected_start_time=2,
              expected_update_time=3,
              expected_end_time=4,
          )))

  executable = common_pb2.Executable(cipd_package='CIPD_PACKAGE',
                                     cipd_version='version')
  yield api.test(
      'with-executable',
      api.test_util.test_child_build('amd64-generic', exe=executable).build,
      api.properties(
          TestProperties(expected_project='chromeos',
                         expected_bucket='postsubmit',
                         expected_builder='amd64-generic-postsubmit',
                         expected_build_target='amd64-generic',
                         expect_commit=True, expected_executable=executable)))

  yield api.test(
      'critical-child',
      api.test_util.test_child_build('amd64-generic', critical='YES').build,
      api.properties(
          TestProperties(expected_project='chromeos',
                         expected_bucket='postsubmit',
                         expected_builder='amd64-generic-postsubmit',
                         expected_build_target='amd64-generic',
                         expected_critical=common_pb2.YES, expect_commit=True)))

  yield api.test(
      'non-critical-child',
      api.test_util.test_child_build('amd64-generic', critical='NO').build,
      api.properties(
          TestProperties(expected_project='chromeos',
                         expected_bucket='postsubmit',
                         expected_builder='amd64-generic-postsubmit',
                         expected_build_target='amd64-generic',
                         expected_critical=common_pb2.NO, expect_commit=True)))

  yield api.test(
      'with-output-properties-message',
      api.test_util.test_build(
          builder='amd64-generic-postsubmit',
          input_properties=BuildMenuProperties(
              build_target=BuildTarget(name='amd64-generic')),
          output_properties=BuildMenuProperties(
              build_target=BuildTarget(name='changed'))).build,
      api.properties(
          TestProperties(expected_project='chromeos',
                         expected_bucket='postsubmit',
                         expected_builder='amd64-generic-postsubmit',
                         expected_build_target='amd64-generic',
                         expected_output_build_target_name='changed',
                         expect_commit=True)))
