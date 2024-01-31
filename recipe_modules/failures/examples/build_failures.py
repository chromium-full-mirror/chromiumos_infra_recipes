# -*- coding: utf-8 -*-
# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

import collections

from PB.chromiumos import builder_config
from PB.go.chromium.org.luci.buildbucket.proto.common import Trinary
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.failures.examples.build_failures import BuildProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'recipe_engine/step',
    'cros_infra_config',
    'failures',
    'naming',
    'urls',
    'test_util',
]


PROPERTIES = BuildProperties


def RunSteps(api, properties):
  # failures._get_failures() sorts the failing builds by title.
  expected_failing_builds = sorted(properties.expected_failing_builds,
                                   key=api.naming.get_build_title)

  if len(properties.builds) == 1:
    api.assertions.assertEqual(
        api.failures.is_critical_build_failure(properties.builds[0]),
        properties.expected_is_critical_build_failure)

  expected_failures = [
      api.failures.Failure('build', x.builder.builder,
                           api.urls.get_build_link_map(x), x.critical,
                           x.builder.builder) for x in expected_failing_builds
  ]
  expected_successful_builds = [
      f for f in properties.builds if f.status == common_pb2.SUCCESS
  ]

  build_results = api.failures.get_build_results(
      properties.builds, properties.refresh_config,
      api.properties['relevant_child_builder_names'])

  api.assertions.assertEqual(expected_failures, build_results.failures)
  api.assertions.assertEqual(
      {'build': len(expected_successful_builds)},
      build_results.successes,
  )


def GenTests(api):
  builder_info = collections.namedtuple(
      'builder_info',
      ['target', 'status', 'critical', 'config_critical', 'message', 'config'])

  def make_builder_info(target, status, critical, config_critical):
    """Define a builder_info for our tests.

    Args:
      target (str): The build target name.
      status (str): The status of the build.
      critical (Trinary.keys): Is the build critical?  'YES', 'NO', or 'UNSET'.
      config_critical (str): What does the builder_config say? 'YES', 'NO', or
        None to have no BuilderConfig for the builder.
    Returns:
      (builder_info) Containing the arguments passed, as well as the Build
        and BuilderConfig messages.
    """
    message = api.test_util.test_child_build(
        target, status=status, critical=Trinary.Value(critical)).message
    config = None
    if config_critical:
      config = builder_config.BuilderConfig()
      config.id.name = '%s-postsubmit' % target
      config.general.critical.value = config_critical == 'YES'
    return builder_info(target, status, critical, config_critical, message,
                        config)

  def test(name, builds, refresh_config=False, expected_failing_builds=None,
           expected_is_critical_build_failure=False,
           relevant_child_builder_names=None):
    """Create a test.

    Args:
      name (str): The test name.
      builds (list[builder_info]): The builds to for get_build_results().
      refresh_config (bool): Whether to have get_build_results refresh the
        config.
      expected_failing_builds (list[builder_info]): The builds that we expect to
        have failed.
      expected_is_critical_build_failure (bool): The expected return from
        api.failures.is_critical_build_failure.

    Returns:
      TestData for the test.
    """
    configs = builder_config.BuilderConfigs()
    props = BuildProperties(
        refresh_config=refresh_config,
        expected_is_critical_build_failure=expected_is_critical_build_failure)

    for build in builds:
      props.builds.add().CopyFrom(build.message)
      if build.config:
        configs.builder_configs.add().CopyFrom(build.config)

    for fail in expected_failing_builds or []:
      failing_build = props.expected_failing_builds.add()
      failing_build.CopyFrom(fail.message)
      if refresh_config:
        failing_build.critical = fail.config_critical == 'YES'

    ret = api.test(
        name,
        api.test_util.test_orchestrator().build,
        api.properties(
            props, relevant_child_builder_names=relevant_child_builder_names))

    if refresh_config:
      ret += api.cros_infra_config.override_builder_configs_test_data(configs)
    return ret

  # Define some builds.
  build_success = make_builder_info('zork', 'SUCCESS', 'UNSET', 'UNSET')
  build_failure = make_builder_info('coral', 'FAILURE', 'NO', 'UNSET')
  build_crit_failure = make_builder_info('eve', 'FAILURE', 'YES', 'YES')
  crit_infra_failure = make_builder_info('bob', 'INFRA_FAILURE', 'YES', 'YES')
  build_was_crit_failure = make_builder_info('grunt', 'FAILURE', 'YES', 'NO')
  build_now_missing_failure = make_builder_info('amd64', 'FAILURE', 'YES', None)

  yield test('success', [build_success])

  yield test('failure', [build_failure])

  yield test('relevant-failure', [build_failure],
             relevant_child_builder_names=[build_failure.config.id.name])

  yield test('critical-failure', [build_crit_failure], expected_failing_builds=[
      build_crit_failure,
  ], expected_is_critical_build_failure=True)

  yield test('relevant-critical-failure', [build_crit_failure],
             expected_failing_builds=[
                 build_crit_failure,
             ], expected_is_critical_build_failure=True,
             relevant_child_builder_names=[build_crit_failure.config.id.name])

  yield test('critical-infra-failure', [crit_infra_failure],
             expected_failing_builds=[
                 crit_infra_failure,
             ], expected_is_critical_build_failure=True)

  # Verify that no-longer-critical and now-missing builder failures are still
  # marked fatal when we do not refresh config.
  yield test(
      'critical-failure-no-refresh',
      [build_crit_failure, build_was_crit_failure, build_now_missing_failure],
      expected_failing_builds=[
          build_crit_failure, build_was_crit_failure, build_now_missing_failure
      ])

  # Verify that no-longer-critical and now-missing builder failures are marked
  # non-fatal when we refresh config.
  yield test(
      'critical-failure-with-refresh',
      [build_crit_failure, build_was_crit_failure, build_now_missing_failure],
      refresh_config=True, expected_failing_builds=[
          build_crit_failure, build_was_crit_failure, build_now_missing_failure
      ])
