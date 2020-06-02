# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'test_util',
]

from PB.chromite.api.depgraph import DepGraph
from PB.chromiumos import common
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.test_util.examples.full import TestProperties

PROPERTIES = TestProperties


def RunSteps(api, properties):
  api.assertions.assertEqual(api.buildbucket.build.builder.project,
                             properties.expected_project)
  api.assertions.assertEqual(api.buildbucket.build.builder.bucket,
                             properties.expected_bucket)
  api.assertions.assertEqual(api.buildbucket.build.builder.builder,
                             properties.expected_builder)
  # Check host for "True"-ness to see if it is set.  We do not care what the
  # value is for the purposes of testing, since we do not want to hard code the
  # answer that buildbucket defaults to.
  if properties.expect_commit:
    api.assertions.assertTrue(api.buildbucket.gitiles_commit.host)
  else:
    api.assertions.assertFalse(api.buildbucket.gitiles_commit.host)

  api.assertions.assertEqual(
      len(api.buildbucket.build.input.gerrit_changes),
      properties.expected_cl_count)

  api.assertions.assertNotEqual(0, api.buildbucket.build.create_time.seconds)
  api.assertions.assertEqual(0, api.buildbucket.build.start_time.seconds)
  api.assertions.assertEqual(0, api.buildbucket.build.update_time.seconds)
  api.assertions.assertEqual(0, api.buildbucket.build.end_time.seconds)

  if properties.expected_executable:
    api.assertions.assertEqual(api.buildbucket.build.exe,
                               properties.expected_executable)


def GenTests(api):

  yield api.test(
      'postsubmit-build',
      api.test_util.test_build().build,
      api.properties(
          TestProperties(expected_project='chromeos',
                         expected_bucket='postsubmit',
                         expected_builder='amd64-generic-postsubmit',
                         expect_commit=True, expected_cl_count=0)))

  # Also verify that project and bucket are handled correctly.
  yield api.test(
      'cq-build',
      api.test_util.test_build(project='myproject', bucket='bucket',
                               cq=True).build,
      api.properties(
          TestProperties(expected_project='myproject', expected_bucket='bucket',
                         expected_builder='amd64-generic-bucket',
                         expected_cl_count=1)))

  # Also verify that builder is handled correctly.
  yield api.test(
      'cq-build-multiple-changes',
      api.test_util.test_build(
          cq=True, builder='my-builder',
          extra_changes=[common_pb2.GerritChange(change=5555)]).build,
      api.properties(
          TestProperties(expected_project='chromeos', expected_bucket='cq',
                         expected_builder='my-builder', expected_cl_count=2)))

  # If we want a specific commit on a specific branch, and specific CLs, this is
  # how.
  yield api.test(
      'specific-commit-and-changes',
      api.test_util.test_build(
          bucket='cq', extra_changes=[
              common_pb2.GerritChange(change=5555),
              common_pb2.GerritChange(change=8888),
              common_pb2.GerritChange(change=9999)
          ], git_ref='refs/heads/mybranch', revision='deadbeefdeadbeef').build,
      api.properties(
          TestProperties(expected_project='chromeos', expected_bucket='cq',
                         expected_builder='amd64-generic-cq',
                         expect_commit=True, expected_cl_count=3)))

  yield api.test(
      'with-times',
      api.test_util.test_build(create_time=1, start_time=2, update_time=3,
                               end_time=4).build,
      api.properties(
          TestProperties(expected_project='chromeos',
                         expected_bucket='postsubmit',
                         expected_builder='amd64-generic-postsubmit',
                         expect_commit=True, expected_cl_count=0)))

  executable = common_pb2.Executable(cipd_package='CIPD_PACKAGE',
                                     cipd_version='version')
  yield api.test(
      'with-executable',
      api.test_util.test_build(exe=executable).build,
      api.properties(
          TestProperties(expected_project='chromeos',
                         expected_bucket='postsubmit',
                         expected_builder='amd64-generic-postsubmit',
                         expect_commit=True, expected_executable=executable,
                         expected_cl_count=0)))
