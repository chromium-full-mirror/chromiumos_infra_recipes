# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from PB.recipe_modules.chromeos.cros_lkgm.examples.do_lkgm import DoLkgmProperties
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/raw_io',
    'recipe_engine/properties',
    'build_menu',
    'cros_infra_config',
    'cros_lkgm',
    'cros_release',
    'cros_snapshot',
    'test_util',
]

PROPERTIES = DoLkgmProperties


def RunSteps(api, properties):
  api.cros_infra_config.configure_builder()

  api.cros_release.create_buildspec(
      gs_location='gs://chromeos-manifest-versions/buildspecs/')
  api.assertions.assertIsNotNone(api.cros_release.buildspec)

  if not properties.skip_public_build:
    api.cros_lkgm.schedule_public_build()
    api.cros_lkgm.collect_public_build()

  api.cros_lkgm.do_lkgm(
      properties.release_builds, lkgm_version='1234.56.0',
      use_branch=properties.use_branch,
      internal_manifest_position=properties.internal_manifest_position,
      external_manifest_position=properties.external_manifest_position)


def GenTests(api):
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
    status = kwargs.pop('status', 'SUCCESS')
    release_builds = kwargs.pop('release_builds', [])
    public_builds = kwargs.pop('public_builds', None)
    use_branch = kwargs.pop('use_branch', False)
    skip_public_build = kwargs.pop('skip_public_build', False)

    if not skip_public_build:
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
        name,
        api.properties(
            DoLkgmProperties(release_builds=release_builds,
                             use_branch=use_branch,
                             skip_public_build=skip_public_build),
            internal_manifest_position=123456,
            external_manifest_position=7654321,
        ),
        api.properties(
            **{
                '$chromeos/cros_lkgm': {
                    'enable_lkgm':
                        True,
                    'builder_threshold_percentage':
                        kwargs.pop('builder_threshold', 50),
                    'full_run':
                        kwargs.pop('full_run', False),
                },
            }), *args, **kwargs, status=status)

  yield api.test(
      'disable-lkgm',
      api.test_util.test_orchestrator(
          bucket='release', builder='release-main-orchestrator').build,
      api.properties(**{
          '$chromeos/cros_lkgm': {
              'enable_lkgm': False,
          },
      }),
      api.post_check(post_process.DoesNotRun, 'assess LKGM readiness'),
      api.post_process(post_process.DropExpectation),
  )
  yield api.test(
      'disable-legacy',
      api.test_util.test_orchestrator(
          bucket='release', builder='release-main-orchestrator').build,
      api.properties(**{
          '$chromeos/cros_lkgm': {
              'enable_lkgm': True,
              'disable_legacy': True,
          },
      }),
      api.post_check(post_process.DoesNotRun, 'assess LKGM readiness'),
      api.post_process(post_process.DropExpectation),
  )

  yield lgkm_test(
      'lkgm-candidate',
      api.test_util.test_orchestrator(
          bucket='release', builder='release-main-orchestrator').build,
      api.post_check(post_process.StepTextContains,
                     'assess LKGM readiness.assess release build results',
                     ['60.00%', '50%']),
      api.post_check(post_process.StepTextContains,
                     'assess LKGM readiness.assess public build results',
                     ['70.00%', '50%']),
      api.post_check(post_process.StepTextEquals, 'assess LKGM readiness',
                     'LKGM candidate'),
      api.post_check(post_process.StepCommandContains,
                     'call chrome_chromeos_lkgm', [
                         '--lkgm',
                         '1234.56.0',
                         '--buildbucket-id',
                         '8945511751514863184',
                         '--debug',
                     ]), api.post_process(post_process.DropExpectation),
      release_builds=create_builds(6, 4),
      public_builds=create_builds(7, 3, start_id=PUBLIC_BUILDER_START_ID),
      full_run=True)

  yield lgkm_test(
      'lkgm-candidate-branch',
      api.test_util.test_orchestrator(
          bucket='release', builder='release-main-orchestrator').build,
      api.post_check(post_process.StepTextContains,
                     'assess LKGM readiness.assess release build results',
                     ['60.00%', '50%']),
      api.post_check(post_process.StepTextContains,
                     'assess LKGM readiness.assess public build results',
                     ['70.00%', '50%']),
      api.post_check(post_process.StepTextEquals, 'assess LKGM readiness',
                     'LKGM candidate'),
      api.post_check(
          post_process.StepCommandContains, 'call chrome_chromeos_lkgm', [
              '--lkgm', '1234.56.0', '--buildbucket-id', '8945511751514863184',
              '--debug', '--branch', 'refs/branch-heads/5615'
          ]), api.post_process(post_process.DropExpectation),
      release_builds=create_builds(6, 4),
      public_builds=create_builds(7, 3, start_id=PUBLIC_BUILDER_START_ID),
      full_run=True, use_branch=True)

  yield lgkm_test(
      'lkgm-candidate-branch-failure',
      api.test_util.test_orchestrator(
          bucket='release', builder='release-main-orchestrator').build,
      api.post_check(post_process.StepTextContains,
                     'assess LKGM readiness.assess release build results',
                     ['60.00%', '50%']),
      api.post_check(post_process.StepTextContains,
                     'assess LKGM readiness.assess public build results',
                     ['70.00%', '50%']),
      api.post_check(post_process.StepTextEquals, 'assess LKGM readiness',
                     'LKGM candidate'),
      api.step_data(
          'fetch chrome branch from chromiumdash.curl fetch_milestones',
          api.raw_io.stream_output('foo\n')),
      api.post_check(post_process.StepFailure,
                     'fetch chrome branch from chromiumdash'),
      api.post_process(post_process.DropExpectation),
      release_builds=create_builds(6, 4),
      public_builds=create_builds(7, 3, start_id=PUBLIC_BUILDER_START_ID),
      full_run=True,
      use_branch=True,
      status='FAILURE',
  )

  yield lgkm_test(
      'lkgm-candidate-dry-run',
      api.test_util.test_orchestrator(
          bucket='release', builder='release-main-orchestrator').build,
      api.post_check(post_process.StepTextContains,
                     'assess LKGM readiness.assess release build results',
                     ['60.00%', '50%']),
      api.post_check(post_process.StepTextContains,
                     'assess LKGM readiness.assess public build results',
                     ['70.00%', '50%']),
      api.post_check(post_process.StepTextEquals, 'assess LKGM readiness',
                     'LKGM candidate'),
      api.post_check(post_process.StepCommandContains,
                     'call chrome_chromeos_lkgm', [
                         '--lkgm', '1234.56.0', '--buildbucket-id',
                         '8945511751514863184', '--debug', '--dryrun'
                     ]), api.post_process(post_process.DropExpectation),
      release_builds=create_builds(6, 4),
      public_builds=create_builds(7, 3, start_id=PUBLIC_BUILDER_START_ID))

  yield lgkm_test(
      'not-lkgm-candidate-release-threshold',
      api.test_util.test_orchestrator(
          bucket='release', builder='release-main-orchestrator').build,
      api.post_check(post_process.StepTextContains,
                     'assess LKGM readiness.assess release build results',
                     ['40.00%', '50%']),
      api.post_check(post_process.StepTextEquals,
                     'assess LKGM readiness.assess public build results',
                     'no public builds'),
      api.post_check(post_process.StepTextEquals, 'assess LKGM readiness',
                     'not an LKGM candidate'),
      api.post_process(post_process.DropExpectation),
      release_builds=create_builds(4, 6), public_builds=None)

  yield lgkm_test(
      'not-lkgm-candidate-release-no-builds',
      api.test_util.test_orchestrator(
          bucket='release', builder='release-main-orchestrator').build,
      api.post_check(post_process.StepTextEquals,
                     'assess LKGM readiness.assess release build results',
                     'no release builds'),
      api.post_check(post_process.StepTextEquals,
                     'assess LKGM readiness.assess public build results',
                     'no public builds'),
      api.post_check(post_process.StepTextEquals, 'assess LKGM readiness',
                     'not an LKGM candidate'),
      api.post_process(post_process.DropExpectation), release_builds=[],
      public_builds=None)

  yield lgkm_test(
      'not-lkgm-candidate-public-threshold',
      api.test_util.test_orchestrator(
          bucket='release', builder='release-main-orchestrator').build,
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
          bucket='release', builder='release-main-orchestrator').build,
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

  yield lgkm_test(
      'absence-of-chromium-branch',
      api.test_util.test_orchestrator(
          bucket='release', builder='release-main-orchestrator').build,
      api.post_check(post_process.StepTextEquals, 'assess LKGM readiness',
                     'LKGM candidate'),
      api.post_check(post_process.MustRun,
                     "skipping uprev: chromium branch doesn't exist"),
      api.step_data(
          'fetch chrome branch from chromiumdash.curl fetch_milestones',
          api.raw_io.stream_output('[{}]\n')),
      release_builds=create_builds(1, 0),
      public_builds=create_builds(1, 0, start_id=PUBLIC_BUILDER_START_ID),
      use_branch=True, simulate_absence_of_chromium_branch=True, full_run=True)

  yield lgkm_test(
      'snapshot',
      api.test_util.test_orchestrator(bucket='postsubmit',
                                      builder='snapshot-orchestrator').build,
      api.cros_snapshot.simulated_snapshot_identifier(
          9999999, 'create buildspec.read chromeos version.read snapshot'),
      api.post_check(post_process.StepTextEquals, 'assess LKGM readiness',
                     'LKGM candidate'), release_builds=create_builds(2, 1),
      skip_public_build=True, full_run=True)

  yield lgkm_test(
      'snapshot-not-candidate',
      api.test_util.test_orchestrator(bucket='postsubmit',
                                      builder='snapshot-orchestrator').build,
      api.cros_snapshot.simulated_snapshot_identifier(
          9999999, 'create buildspec.read chromeos version.read snapshot'),
      api.post_check(post_process.StepTextEquals, 'assess LKGM readiness',
                     'not an LKGM candidate'),
      release_builds=create_builds(1, 2), skip_public_build=True, full_run=True)

  # Test the case of failure on `chrome_chromeos_lkgm` script call.
  yield lgkm_test(
      'lkgm-script-failed',
      api.test_util.test_orchestrator(
          bucket='release', builder='release-main-orchestrator').build,
      api.step_data('call chrome_chromeos_lkgm',
                    retcode=1), release_builds=create_builds(1, 0),
      skip_public_build=True, status='FAILURE')
