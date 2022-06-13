# -*- coding: utf-8 -*-
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'build_menu',
    'cros_lkgm',
    'cros_infra_config',
    'cros_release',
    'test_util',
]

from recipe_engine import post_process
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from PB.recipe_modules.chromeos.cros_lkgm.examples.do_lkgm import (
    DoLkgmProperties)

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'
PROPERTIES = DoLkgmProperties


def RunSteps(api, properties):
  api.cros_infra_config.configure_builder()

  api.cros_release.create_buildspec(
      gs_location='gs://chromeos-manifest-versions/buildspecs/')
  api.assertions.assertIsNotNone(api.cros_release.buildspec)

  api.cros_lkgm.schedule_public_build()
  api.cros_lkgm.collect_public_build()
  api.cros_lkgm.do_lkgm(properties.release_builds)


def GenTests(api):

  def step_command_has_substr(check, step_odict, step, substring):
    check('command line for step %s contained %s' % (step, substring),
          any([substring in token for token in step_odict[step].cmd]))

  PUBLIC_BUILDER_START_ID = 8922054662172514001

  def create_builds(num_success, num_failure, start_id=1):
    builds = []
    bbid = start_id
    for _ in range(num_success):
      builds.append(build_pb2.Build(id=bbid, status=common_pb2.SUCCESS))
      bbid += 1
    for _ in range(num_failure):
      builds.append(build_pb2.Build(id=bbid, status=common_pb2.FAILURE))
      bbid += 1
    return builds

  def lgkm_test(name, *args, **kwargs):
    release_builds = kwargs.pop('release_builds', [])
    public_builds = kwargs.pop('public_builds', None)

    output = build_pb2.Build.Output()
    if public_builds is not None:
      child_build_ids = [
          str(PUBLIC_BUILDER_START_ID + x) for x in range(len(public_builds))
      ]
      output.properties.update({'child_builds': child_build_ids})
    public_orch_status = kwargs.pop('public_orch_status', common_pb2.SUCCESS)
    public_orch = build_pb2.Build(id=8922054662172514000, output=output,
                                  status=public_orch_status)

    args = list(args)
    args.append(
        api.buildbucket.simulated_collect_output(
            [public_orch], step_name='collect public orchestrator.collect'))
    if public_builds is not None:
      args.append(
          api.buildbucket.simulated_get_multi(
              public_builds,
              step_name='assess LKGM readiness.assess public build results.get public builders',
          ))

    return api.test(
        name, api.properties(DoLkgmProperties(release_builds=release_builds)),
        api.properties(
            **{
                '$chromeos/cros_lkgm': {
                    'builder_threshold_percentage':
                        kwargs.pop('builder_threshold', 50),
                    'full_run':
                        kwargs.pop('full_run', False),
                    'presubmit_trybots':
                        kwargs.pop('presubmit_trybots', []),
                },
            }), *args, **kwargs)

  yield lgkm_test(
      'lkgm-candidate',
      api.test_util.test_orchestrator(
          bucket='release', builder='main-release-orchestrator').build,
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.StepTextContains,
                     'assess LKGM readiness.assess release build results',
                     ['60.00%', '50%']),
      api.post_check(post_process.StepTextContains,
                     'assess LKGM readiness.assess public build results',
                     ['70.00%', '50%']),
      api.post_check(post_process.StepTextEquals, 'assess LKGM readiness',
                     'LKGM candidate'),
      api.post_check(
          step_command_has_substr,
          'create LKGM CL.commit in chromium/src.write commit message',
          '1234.56.0'),
      api.post_check(
          step_command_has_substr,
          'create LKGM CL.commit in chromium/src.write commit message',
          'CQ_INCLUDE_TRYBOTS=luci.chrome.try:chromeos-eve-chrome'),
      api.post_check(step_command_has_substr,
                     'create LKGM CL.create CL.set labels on CL 1.git push',
                     'Commit-Queue+2'),
      api.post_process(post_process.DropExpectation),
      release_builds=create_builds(6, 4),
      public_builds=create_builds(7, 3, start_id=PUBLIC_BUILDER_START_ID),
      full_run=True, presubmit_trybots=['chromeos-eve-chrome'])

  yield lgkm_test(
      'lkgm-candidate-dry-run',
      api.test_util.test_orchestrator(
          bucket='release', builder='main-release-orchestrator').build,
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.StepTextContains,
                     'assess LKGM readiness.assess release build results',
                     ['60.00%', '50%']),
      api.post_check(post_process.StepTextContains,
                     'assess LKGM readiness.assess public build results',
                     ['70.00%', '50%']),
      api.post_check(post_process.StepTextEquals, 'assess LKGM readiness',
                     'LKGM candidate'),
      api.post_check(step_command_has_substr,
                     'create LKGM CL.create CL.set labels on CL 1.git push',
                     'Commit-Queue+1'),
      api.post_process(post_process.DropExpectation),
      release_builds=create_builds(6, 4),
      public_builds=create_builds(7, 3, start_id=PUBLIC_BUILDER_START_ID))

  yield lgkm_test(
      'not-lkgm-candidate-release-threshold',
      api.test_util.test_orchestrator(
          bucket='release', builder='main-release-orchestrator').build,
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.StepTextContains,
                     'assess LKGM readiness.assess release build results',
                     ['40.00%', '50%']),
      api.post_check(post_process.DoesNotRun,
                     'assess LKGM readiness.assess public build results'),
      api.post_check(post_process.StepTextEquals, 'assess LKGM readiness',
                     'not an LKGM candidate'),
      api.post_process(post_process.DropExpectation),
      release_builds=create_builds(4, 6), public_builds=None)

  yield lgkm_test(
      'not-lkgm-candidate-release-no-builds',
      api.test_util.test_orchestrator(
          bucket='release', builder='main-release-orchestrator').build,
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.StepTextEquals,
                     'assess LKGM readiness.assess release build results',
                     'no release builds'),
      api.post_check(post_process.DoesNotRun,
                     'assess LKGM readiness.assess public build results'),
      api.post_check(post_process.StepTextEquals, 'assess LKGM readiness',
                     'not an LKGM candidate'),
      api.post_process(post_process.DropExpectation), release_builds=[],
      public_builds=None)

  yield lgkm_test(
      'not-lkgm-candidate-public-threshold',
      api.test_util.test_orchestrator(
          bucket='release', builder='main-release-orchestrator').build,
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.StepTextContains,
                     'assess LKGM readiness.assess release build results',
                     ['60.00%', '50%']),
      api.post_check(post_process.StepTextContains,
                     'assess LKGM readiness.assess public build results',
                     ['30.00%', '50%']),
      api.post_check(post_process.StepTextEquals, 'assess LKGM readiness',
                     'not an LKGM candidate'),
      api.post_process(post_process.DropExpectation),
      release_builds=create_builds(6, 4),
      public_builds=create_builds(3, 7, start_id=PUBLIC_BUILDER_START_ID))

  yield lgkm_test(
      'not-lkgm-candidate-public-no-builds',
      api.test_util.test_orchestrator(
          bucket='release', builder='main-release-orchestrator').build,
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.StepTextContains,
                     'assess LKGM readiness.assess release build results',
                     ['60.00%', '50%']),
      api.post_check(post_process.StepTextContains,
                     'assess LKGM readiness.assess public build results',
                     ['any child builds']),
      api.post_check(post_process.StepTextEquals, 'assess LKGM readiness',
                     'not an LKGM candidate'),
      api.post_process(post_process.DropExpectation),
      public_orch_status=common_pb2.FAILURE, release_builds=create_builds(6, 4),
      public_builds=None)
