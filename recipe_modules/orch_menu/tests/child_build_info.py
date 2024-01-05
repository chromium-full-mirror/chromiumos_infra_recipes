# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the add_child_build_info_to_output_property function."""

from google.protobuf import json_format
from google.protobuf import timestamp_pb2

from PB.chromiumos import common as common_pb2
from PB.recipe_modules.chromeos.failures.failures import PackageFailure

from recipe_engine import post_process

DEPS = [
    'recipe_engine/buildbucket',
    'cros_test_proctor',
    'orch_menu',
    'test_util',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api):
  with api.orch_menu.setup_orchestrator():
    api.orch_menu.add_child_info_to_output_property()


def GenTests(api):

  def _child_builds(child_builder_names, async_unit_tests_enabled=False,
                    props=None):
    props = props or {}
    if async_unit_tests_enabled:
      props.update({
          'image_artifacts_uploaded_time':
              json_format.MessageToDict(timestamp_pb2.Timestamp(seconds=101))
      })
    builds = [
        api.test_util.test_build(build_id=101 + i, cq=True, builder=builder,
                                 output_properties=props).message
        for i, builder in enumerate(child_builder_names)
    ]
    return builds

  yield api.test(
      'basic',
      api.buildbucket.try_build(project='chromeos', bucket='cq',
                                builder='cq-orchestrator'),
      api.buildbucket.simulated_search_results(_child_builds(['atlas-cq'])),
      api.post_check(post_process.PropertyEquals, 'child_builds', ['101']),
      api.post_check(lambda check, steps: check(steps[
          'set child_build_info'].output_properties['child_build_info'][0][
              'tested_in_this_run'] is False)),
      api.post_check(lambda check, steps: check(
          'image_artifacts_uploaded_time' not in steps['set child_build_info'].
          output_properties['child_build_info'][0])),
      api.post_check(lambda check, steps: check('package_failures' not in steps[
          'set child_build_info'].output_properties['child_build_info'][0])),
      api.post_process(post_process.DropExpectation),
  )

  package_failures = [
      json_format.MessageToDict(
          PackageFailure(
              package=common_pb2.PackageInfo(category='foo',
                                             package_name='bar'),
              phase=PackageFailure.COMPILE))
  ]
  yield api.test(
      'package-failures',
      api.buildbucket.try_build(project='chromeos', bucket='cq',
                                builder='cq-orchestrator'),
      api.buildbucket.simulated_search_results(
          _child_builds(['atlas-cq'],
                        props={'package_failures': package_failures})),
      api.post_check(lambda check, steps: check(steps[
          'set child_build_info'].output_properties['child_build_info'][0][
              'package_failures'] == package_failures)),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'tested-in-this-run',
      api.buildbucket.try_build(project='chromeos', bucket='cq',
                                builder='cq-orchestrator'),
      api.buildbucket.simulated_search_results(
          _child_builds(['atlas-cq', 'dedede-cq'])),
      api.cros_test_proctor.builders_tested_in_this_run(['atlas-cq']),
      api.post_check(post_process.PropertyEquals, 'child_builds',
                     ['101', '102']),
      # atlas-cq
      api.post_check(lambda check, steps: check(steps[
          'set child_build_info'].output_properties['child_build_info'][0][
              'tested_in_this_run'] is True)),
      # dedede-cq
      api.post_check(lambda check, steps: check(steps[
          'set child_build_info'].output_properties['child_build_info'][1][
              'tested_in_this_run'] is False)),
      api.post_check(lambda check, steps: check(
          'image_artifacts_uploaded_time' not in steps['set child_build_info'].
          output_properties['child_build_info'][0])),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'cq-async-unit-testing',
      api.buildbucket.try_build(project='chromeos', bucket='cq',
                                builder='cq-orchestrator'),
      api.buildbucket.simulated_search_results(
          _child_builds(['atlas-cq'], async_unit_tests_enabled=True)),
      api.post_check(lambda check, steps: check(steps[
          'set child_build_info'].output_properties['child_build_info'][0][
              'image_artifacts_uploaded_time'] == json_format.MessageToDict(
                  timestamp_pb2.Timestamp(seconds=101)))),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'snapshot-orchestrator-relevance-field',
      api.buildbucket.ci_build(project='chromeos', bucket='snapshot',
                               builder='snapshot-orchestrator'),
      api.buildbucket.simulated_search_results(
          _child_builds(['atlas-postsubmit'])),
      api.post_check(lambda check, steps: check(steps[
          'set child_build_info'].output_properties['child_build_info'][0][
              'relevant'] is False)),
      api.post_process(post_process.DropExpectation),
  )

  yield api.test(
      'postsubmit-orchestrator-no-relevance-field',
      api.buildbucket.ci_build(project='chromeos', bucket='postsubmit',
                               builder='postsubmit-orchestrator'),
      api.buildbucket.simulated_search_results(
          _child_builds(['atlas-postsubmit'])),
      api.post_check(lambda check, steps: check('relevant' not in steps[
          'set child_build_info'].output_properties['child_build_info'][0])),
      api.post_process(post_process.DropExpectation),
  )
