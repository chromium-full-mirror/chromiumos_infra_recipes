# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=missing-module-docstring
# TODO(b/303696694): Add a simple docstring here.

from google.protobuf.json_format import MessageToJson

from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos import common as common_pb2
from PB.chromiumos.build_report import BuildReport
from PB.chromiumos.builder_config import BuilderConfig
from PB.go.chromium.org.luci.buildbucket.proto import build as build_pb2
from PB.recipe_modules.chromeos.cros_release.cros_release import CrosReleaseProperties
from PB.recipe_modules.chromeos.cros_version.cros_version import CrosVersionProperties
from recipe_engine import post_process

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/buildbucket',
    'recipe_engine/properties',
    'recipe_engine/step',
    'build_menu',
    'build_reporting',
    'cros_release',
    'git',
    'mutable_output',
    'signing',
    'test_util',
]



def RunSteps(api):
  with api.mutable_output.wrap():
    # Manufacture the minimal builder config.
    config = BuilderConfig(
        id=BuilderConfig.Id(name='kukui-release',
                            type=BuilderConfig.Id.RELEASE),
        artifacts=BuilderConfig.Artifacts(
            artifacts_info=common_pb2.ArtifactsByService(
                legacy=common_pb2.ArtifactsByService.Legacy(output_artifacts=[
                    common_pb2.ArtifactsByService.Legacy.ArtifactInfo(
                        gs_locations=[
                            'chromeos-image-archive/{target}-release/{version}'
                        ])
                ]),
            )))
    sysroot = Sysroot(build_target=common_pb2.BuildTarget(name='kukui'))

    if api.signing.local_signing:
      release_sign_types = api.cros_release.sign_types
      channels = api.cros_release.channels
      _ = api.signing.sign_artifacts(sign_types=release_sign_types,
                                     channels=channels)
      with api.step.nest('set up bucket metadata') as step:
        api.cros_release.emit_release_buckets(sysroot.build_target.name, step)
    else:
      # Test data for instruction files are defined in
      # recipe_modules/cros_build_api/test_api.py.
      _, instructions = api.cros_release.push_and_sign_images(config, sysroot)
      api.assertions.assertEqual(
          instructions,
          [
              'gs://chromeos-releases/beta-channel/grunt/14493.0.0/ChromeOS-recovery-R100-14493.0.0-grunt.instructions',
              'gs://chromeos-releases/beta-channel/grunt/14493.0.0/ChromeOS-base-R100-14493.0.0-grunt.instructions',
          ],
      )

    api.build_reporting.set_build_type(BuildReport.BUILD_TYPE_RELEASE,
                                       'build_target')
    api.cros_release.check_buildspec()

    api.cros_release.set_output_properties()
    if 'bcid_fail' in api.properties and api.properties['bcid_fail']:
      api.mutable_output(bcid={'existing': ['failed_artifact']})
    api.cros_release.run_payload_generation(use_split_paygen=True,
                                            skip_n2n_batch=True)


def GenTests(api):
  successful_paygen_orch = build_pb2.Build(id=8922054662172514000,
                                           status='SUCCESS')
  successful_paygen_orch.output.properties['payloads'] = [
      MessageToJson(
          BuildReport.Payload(size=1337),
      )
  ]

  yield api.build_menu.test(
      'basic',
      api.properties(
          **{
              '$chromeos/cros_version':
                  CrosVersionProperties(remove_snapshot_from_version=True),
              '$chromeos/cros_source': {
                  'syncToManifest': {
                      'manifestGsPath':
                          'gs://chromiumos-manifest-versions/buildspecs/99/1234.56.0.xml'
                  }
              },
          }),
      api.post_check(post_process.LogContains,
                     'generate payloads.running paygen orchestrator.schedule',
                     'json.output', ['"bucket": "release"']),
      api.buildbucket.simulated_collect_output(
          [successful_paygen_orch],
          'generate payloads.running paygen orchestrator.collect'),
      api.post_check(
          post_process.LogContains,
          'push images.call chromite.api.ImageService/PushImage', 'request',
          ['gs://chromeos-image-archive/kukui-release/R99-1234.56.0']),
      api.post_check(post_process.LogContains,
                     'generate payloads.running paygen orchestrator.schedule',
                     'request', ['"use_split_paygen": true']),
      api.post_check(post_process.DoesNotRun,
                     'generate payloads.inspect failure'),
      api.test_util.test_child_build('kukui', builder_name='kukui-release-main',
                                     bucket='release').build,
      build_target='kukui',
      builder='kukui-release-main',
      bucket='release',
  )

  yield api.build_menu.test(
      'conductor',
      api.properties(
          **{
              '$chromeos/cros_version':
                  CrosVersionProperties(remove_snapshot_from_version=True),
              '$chromeos/conductor': {
                  'enable_conductor': True,
                  'collect_configs': {
                      'paygen-orch': {},
                  },
              },
              '$chromeos/cros_source': {
                  'syncToManifest': {
                      'manifestGsPath':
                          'gs://chromiumos-manifest-versions/buildspecs/99/1234.56.0.xml'
                  }
              },
          }),
      api.post_check(
          post_process.LogContains,
          'generate payloads.running paygen orchestrator.buildbucket.schedule',
          'json.output', ['"bucket": "try-preprod"']),
      api.buildbucket.simulated_collect_output(
          [successful_paygen_orch],
          'generate payloads.running paygen orchestrator'),
      api.post_check(
          post_process.MustRun,
          'generate payloads.running paygen orchestrator.conductor: collect'),
      api.post_check(
          post_process.LogContains,
          'push images.call chromite.api.ImageService/PushImage', 'request',
          ['gs://chromeos-image-archive/kukui-release/R99-1234.56.0']),
      api.post_check(post_process.DoesNotRun,
                     'generate payloads.inspect failure'),
      api.test_util.test_child_build('kukui', builder_name='kukui-release-main',
                                     bucket='try-preprod').build)

  paygen_partial_failure = build_pb2.Build(
      id=8922054662172514000, status='FAILURE',
      summary_markdown='1 of 2 passed\n\nhttps://cr-buildbucket.appspot.com/build/8812345678901234567'
  )
  paygen_partial_failure.output.properties['payloads'] = [
      MessageToJson(
          BuildReport.Payload(size=1337),
      )
  ]

  yield api.build_menu.test(
      'paygen-failure',
      api.properties(
          **{
              '$chromeos/cros_version':
                  CrosVersionProperties(remove_snapshot_from_version=True),
              '$chromeos/cros_release':
                  CrosReleaseProperties(channels=[common_pb2.CHANNEL_BETA],
                                        src_paygen_bucket='chromeos-releases',
                                        minios_unsupported=True),
              '$chromeos/cros_source': {
                  'syncToManifest': {
                      'manifestGsPath':
                          'gs://chromiumos-manifest-versions/buildspecs/99/1234.56.0.xml'
                  }
              },
          }),
      api.post_check(
          post_process.LogContains,
          'push images.call chromite.api.ImageService/PushImage', 'request',
          ['gs://chromeos-image-archive/kukui-release/R99-1234.56.0']),
      api.post_check(post_process.LogContains,
                     'generate payloads.running paygen orchestrator.schedule',
                     'json.output', ['"bucket": "release"']),
      api.buildbucket.simulated_collect_output(
          [paygen_partial_failure],
          'generate payloads.running paygen orchestrator.collect'),
      api.post_check(post_process.MustRun,
                     'generate payloads.build status pubsub update'),
      api.post_check(post_process.StepFailure, 'generate payloads'),
      api.post_check(post_process.StepFailure,
                     'generate payloads.inspect failure'),
      api.test_util.test_child_build('kukui', builder_name='kukui-release-main',
                                     bucket='release').build,
      status='FAILURE',
  )

  yield api.build_menu.test(
      'paygen-infra-failure',
      api.properties(
          **{
              '$chromeos/cros_version':
                  CrosVersionProperties(remove_snapshot_from_version=True),
              '$chromeos/cros_release':
                  CrosReleaseProperties(channels=[common_pb2.CHANNEL_BETA],
                                        src_paygen_bucket='chromeos-releases'),
              '$chromeos/cros_source': {
                  'syncToManifest': {
                      'manifestGsPath':
                          'gs://chromiumos-manifest-versions/buildspecs/99/1234.56.0.xml'
                  }
              },
          }),
      api.post_check(
          post_process.LogContains,
          'push images.call chromite.api.ImageService/PushImage', 'request',
          ['gs://chromeos-image-archive/kukui-release/R99-1234.56.0']),
      api.post_check(post_process.LogContains,
                     'generate payloads.running paygen orchestrator.schedule',
                     'json.output', ['"bucket": "release"']),
      api.buildbucket.simulated_collect_output([
          build_pb2.Build(
              id=8922054662172514000, status='INFRA_FAILURE',
              summary_markdown='1 of 2 passed\n\nhttps://cr-buildbucket.appspot.com/build/8812345678901234567'
          )
      ], 'generate payloads.running paygen orchestrator.collect'),
      api.post_check(post_process.StepException, 'generate payloads'),
      api.post_check(post_process.StepException,
                     'generate payloads.inspect failure'),
      api.test_util.test_child_build('kukui', builder_name='kukui-release-main',
                                     bucket='release').build,
      api.post_process(post_process.DropExpectation),
      status='INFRA_FAILURE',
      build_target='kukui',
      builder='kukui-release-main',
      bucket='release',
  )

  yield api.build_menu.test(
      'mpa',
      api.properties(
          **{
              '$chromeos/cros_version':
                  CrosVersionProperties(remove_snapshot_from_version=True),
              '$chromeos/cros_source': {
                  'syncToManifest': {
                      'manifestGsPath':
                          'gs://chromiumos-manifest-versions/buildspecs/99/1234.56.0.xml'
                  }
              },
              '$chromeos/cros_release':
                  CrosReleaseProperties(paygen_mpa=True),
              '$chromeos/signing': {
                  'local_signing': True,
                  'bcid_enforcement': {
                      'paygen_input_provenance_verification_fatal': True
                  },
              },
          }),
      api.buildbucket.simulated_collect_output(
          [successful_paygen_orch],
          'generate payloads.running paygen orchestrator.collect'),
      api.test_util.test_child_build('kukui', builder_name='kukui-release-main',
                                     bucket='release').build,
      api.post_check(post_process.LogContains,
                     'generate payloads.running paygen orchestrator.schedule',
                     'request', ['"builder": "paygen-orchestrator-mpa"']),
      api.post_process(post_process.DropExpectation),
      build_target='kukui',
      builder='kukui-release-main',
      bucket='release',
  )

  successful_paygen_orch.output.properties['bcid'] = {
      'failed_payload_input_prov_verification': ['paygen_artifact']
  }
  expected_bcid = {
      "existing": ["failed_artifact"],
      "failed_payload_input_prov_verification": ["paygen_artifact"]
  }
  yield api.build_menu.test(
      'bcid-paygen-props',
      api.properties(
          bcid_fail=True, **{
              '$chromeos/cros_version':
                  CrosVersionProperties(remove_snapshot_from_version=True),
              '$chromeos/cros_source': {
                  'syncToManifest': {
                      'manifestGsPath':
                          'gs://chromiumos-manifest-versions/buildspecs/99/1234.56.0.xml'
                  }
              },
          }),
      api.post_check(post_process.LogContains,
                     'generate payloads.running paygen orchestrator.schedule',
                     'json.output', ['"bucket": "release"']),
      api.buildbucket.simulated_collect_output(
          [successful_paygen_orch],
          'generate payloads.running paygen orchestrator.collect'),
      api.post_check(
          post_process.LogContains,
          'push images.call chromite.api.ImageService/PushImage', 'request',
          ['gs://chromeos-image-archive/kukui-release/R99-1234.56.0']),
      api.post_check(post_process.LogContains,
                     'generate payloads.running paygen orchestrator.schedule',
                     'request', ['"use_split_paygen": true']),
      api.post_check(post_process.DoesNotRun,
                     'generate payloads.inspect failure'),
      api.test_util.test_child_build('kukui', builder_name='kukui-release-main',
                                     bucket='release').build,
      api.post_check(post_process.PropertyEquals, 'bcid', expected_bcid),
      api.post_process(post_process.DropExpectation),
      build_target='kukui',
      builder='kukui-release-main',
      bucket='release',
  )
