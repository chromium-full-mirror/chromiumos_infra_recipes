# Copyright 2025 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for signing_operation."""

from google.protobuf.json_format import MessageToDict, MessageToJson

from PB.chromite.api.image import SignImageResponse
from PB.chromiumos import build_report as build_report_pb2
from PB.chromiumos import signing as signing_pb2
from PB.chromiumos.common import (CHANNEL_CANARY, CHANNEL_DEV,
                                  IMAGE_TYPE_ACCESSORY_RWSIG, IMAGE_TYPE_BASE,
                                  IMAGE_TYPE_FACTORY, IMAGE_TYPE_FIRMWARE,
                                  IMAGE_TYPE_FLEXOR_KERNEL, IMAGE_TYPE_RECOVERY)
from PB.chromiumos.signing import BuildTargetSigningConfigs, BuildTargetSigningConfig, SigningConfig
from PB.recipe_modules.chromeos.signing.signing import SigningProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'build_menu',
    'cros_build_api',
    'cros_infra_config',
    'mutable_output',
    'signing',
]

PASSED = build_report_pb2.BuildReport.SignedBuildMetadata.SIGNING_STATUS_PASSED
FAILED = build_report_pb2.BuildReport.SignedBuildMetadata.SIGNING_STATUS_FAILED


def RunSteps(api: RecipeApi):
  with api.mutable_output.wrap():
    # For coverage, set to the default value.
    api.signing.test_api.signing_config_test_data = api.signing.test_api.signing_config_test_data
    # Fetch config.
    config = api.signing.get_config()
    expected_config = BuildTargetSigningConfig(
        build_target='kukui',
        keyset='kukui-foo-bar',
        signing_configs=[
            SigningConfig(
                image_type=IMAGE_TYPE_BASE,
                keyset='kukui-foo-bar',
                ensure_no_password=True,
                firmware_update=True,
            ),
            SigningConfig(
                image_type=IMAGE_TYPE_FACTORY,
                keyset='kukui-foo-bar-factory',
                ensure_no_password=True,
                firmware_update=True,
            ),
            SigningConfig(
                image_type=IMAGE_TYPE_FIRMWARE,
                ensure_no_password=True,
                firmware_update=True,
            ),
            SigningConfig(
                image_type=IMAGE_TYPE_RECOVERY,
                ensure_no_password=True,
                firmware_update=True,
            ),
            SigningConfig(
                image_type=IMAGE_TYPE_ACCESSORY_RWSIG,
                ensure_no_password=True,
                firmware_update=True,
            ),
            SigningConfig(
                image_type=IMAGE_TYPE_FLEXOR_KERNEL,
                ensure_no_password=True,
                firmware_update=True,
            ),
        ],
    )
    api.assertions.assertEqual(config, expected_config)

    sign_types = [
        IMAGE_TYPE_BASE, IMAGE_TYPE_FIRMWARE, IMAGE_TYPE_RECOVERY,
        IMAGE_TYPE_ACCESSORY_RWSIG, IMAGE_TYPE_FLEXOR_KERNEL
    ]
    channels = [CHANNEL_CANARY, CHANNEL_DEV]

    processed_config, archive_dir = api.signing.setup_signing(
        sign_types, channels)
    api.path.mock_add_file(
        f"{str(archive_dir).replace('1','2')}/chromiumos_test_image.tar.xz")
    api.path.mock_add_file(f"{str(archive_dir).replace('1','2')}/dlc/dlc.img")
    api.assertions.assertEqual(api.signing.get_paygen_keyset(), 'kukui-foo-bar')
    expected_processed_config = BuildTargetSigningConfig(
        build_target='kukui',
        keyset='kukui-foo-bar',
        version='1234.56.0',
        signing_configs=[
            SigningConfig(
                image_type=IMAGE_TYPE_BASE,
                channel=CHANNEL_CANARY,
                keyset='kukui-foo-bar',
                ensure_no_password=True,
                firmware_update=True,
                archive_path='chromiumos_base_image.tar.xz',
                recovery_zip=True,
            ),
            SigningConfig(
                image_type=IMAGE_TYPE_FIRMWARE,
                channel=CHANNEL_CANARY,
                ensure_no_password=True,
                firmware_update=True,
                archive_path='firmware_from_source.tar.bz2',
                recovery_zip=True,
            ),
            SigningConfig(
                image_type=IMAGE_TYPE_RECOVERY,
                channel=CHANNEL_CANARY,
                ensure_no_password=True,
                firmware_update=True,
                archive_path='recovery_image.tar.xz',
                recovery_zip=True,
            ),
            SigningConfig(
                image_type=IMAGE_TYPE_ACCESSORY_RWSIG,
                channel=CHANNEL_CANARY,
                ensure_no_password=True,
                firmware_update=True,
                archive_path='firmware_from_source.tar.bz2',
                recovery_zip=True,
            ),
            SigningConfig(
                image_type=IMAGE_TYPE_FLEXOR_KERNEL,
                channel=CHANNEL_CANARY,
                ensure_no_password=True,
                firmware_update=True,
                archive_path='flexor_vmlinuz.tar.zst',
                recovery_zip=True,
            ),
            SigningConfig(
                image_type=IMAGE_TYPE_BASE,
                channel=CHANNEL_DEV,
                keyset='kukui-foo-bar',
                ensure_no_password=True,
                firmware_update=True,
                archive_path='chromiumos_base_image.tar.xz',
                recovery_zip=True,
            ),
            SigningConfig(
                image_type=IMAGE_TYPE_FIRMWARE,
                channel=CHANNEL_DEV,
                ensure_no_password=True,
                firmware_update=True,
                archive_path='firmware_from_source.tar.bz2',
                recovery_zip=True,
            ),
            SigningConfig(
                image_type=IMAGE_TYPE_RECOVERY,
                channel=CHANNEL_DEV,
                ensure_no_password=True,
                firmware_update=True,
                archive_path='recovery_image.tar.xz',
                recovery_zip=True,
            ),
            SigningConfig(
                image_type=IMAGE_TYPE_ACCESSORY_RWSIG,
                channel=CHANNEL_DEV,
                ensure_no_password=True,
                firmware_update=True,
                archive_path='firmware_from_source.tar.bz2',
                recovery_zip=True,
            ),
            SigningConfig(
                image_type=IMAGE_TYPE_FLEXOR_KERNEL,
                channel=CHANNEL_DEV,
                ensure_no_password=True,
                firmware_update=True,
                archive_path='flexor_vmlinuz.tar.zst',
                recovery_zip=True,
            ),
        ],
    )
    api.assertions.assertEqual(processed_config, expected_processed_config)

    # Call signing.
    with api.step.nest('sign artifacts'):
      api.signing.signing_operation(
          config=BuildTargetSigningConfigs(
              build_target_signing_configs=[processed_config]),
          local_artifact_dir=api.path.start_dir / 'shellball-dir')


def GenTests(api: RecipeTestApi):
  sample_response = SignImageResponse(
      output_archive_dir='/archive_dir/',
      signed_artifacts=signing_pb2.BuildTargetSignedArtifacts(
          archive_artifacts=[
              signing_pb2.ArchiveArtifacts(
                  build_target='kukui',
                  channel=CHANNEL_DEV,
                  signed_artifacts=[
                      signing_pb2.SignedArtifact(
                          signed_artifact_name='foo.bin',
                      ),
                      signing_pb2.SignedArtifact(
                          signed_artifact_name='bad-artifact',
                      )
                  ],
                  signing_status=FAILED,
              ),
              signing_pb2.ArchiveArtifacts(
                  build_target='kukui',
                  channel=CHANNEL_CANARY,
                  signed_artifacts=[
                      signing_pb2.SignedArtifact(
                          signed_artifact_name='bar.bin',
                      ),
                  ],
                  signing_status=PASSED,
              ),
              signing_pb2.ArchiveArtifacts(
                  build_target='kukui',
                  # no channel, gets skipped.
                  signed_artifacts=[
                      signing_pb2.SignedArtifact(
                          signed_artifact_name='no-channel.bin',
                      ),
                  ],
                  signing_status=PASSED,
              )
          ]))

  yield api.build_menu.test(
      'basic',
      api.properties(
          **{
              '$chromeos/signing':
                  MessageToDict(
                      SigningProperties(local_signing=True,
                                        gs_upload_bucket='chromeos-releases'))
          }),
      api.cros_build_api.set_api_return('sign artifacts.call BAPI',
                                        'ImageService/SignImage',
                                        MessageToJson(sample_response)),
      api.step_data(
          'sign artifacts.call BAPI.read cloudkms logs.list [CLEANUP]/signing-dir_tmp_2/cloudkms-logs',
          api.file.listdir([
              '[CLEANUP]/signing-dir_tmp_2/cloudkms-logs/log1',
              '[CLEANUP]/signing-dir_tmp_2/cloudkms-logs/log2',
          ])),
      api.step_data(
          'sign artifacts.call BAPI.read cloudkms logs.read log1',
          api.file.read_text('this is log 1'),
      ),
      api.step_data(
          'sign artifacts.call BAPI.read cloudkms logs.read log2',
          api.file.read_text('this is log 2'),
      ),
      api.post_check(
          post_process.MustRun,
          'sign artifacts.call BAPI.call chromite.api.ImageService/SignImage'),
      api.post_check(post_process.LogContains,
                     'sign artifacts.call BAPI.read cloudkms logs', 'log1',
                     ['this is log 1']),
      api.post_check(post_process.LogContains,
                     'sign artifacts.call BAPI.read cloudkms logs', 'log2',
                     ['this is log 2']),
      api.post_check(post_process.StepFailure, 'sign artifacts.call BAPI'),
      api.post_check(
          post_process.DoesNotRun,
          'sign artifacts.upload signed artifacts to chromeos-releases bucket.upload signed artifacts for CHANNEL_UNSPECIFIED'
      ),
      api.post_check(
          post_process.DoesNotRun,
          'sign artifacts.upload signed artifacts to chromeos-releases bucket.upload signed artifacts for CHANNEL_DEV'
      ),
      api.post_check(
          post_process.DoesNotRun,
          'sign artifacts.upload signed artifacts to chromeos-releases bucket.upload signed artifacts for CHANNEL_CANARY.generate signed provenance'
      ),
      api.post_check(
          post_process.StepCommandContains,
          'sign artifacts.upload signed artifacts to chromeos-releases bucket.upload signed artifacts for CHANNEL_CANARY.gsutil cp',
          [
              '/archive_dir/bar.bin',
              'gs://chromeos-releases/canary-channel/kukui/1234.56.0/'
          ]),
      api.post_process(
          post_process.PropertyEquals, 'bcid', {
              "failed_signed_prov_generation": [],
              "failed_unsigned_prov_verification": []
          }),
      api.post_process(
          post_process.PropertyEquals, 'signed_upload_paths', {
              "canary-channel":
                  "gs://chromeos-releases/canary-channel/kukui/1234.56.0/"
          }), api.post_process(post_process.DropExpectation),
      build_target='kukui', builder='kukui-release-main', status='FAILURE')

  yield api.build_menu.test(
      'cq',
      api.properties(
          **{
              '$chromeos/signing':
                  MessageToDict(
                      SigningProperties(
                          local_signing=True,
                          gs_upload_bucket='chromeos-throw-away-bucket'))
          }),
      api.cros_build_api.set_api_return('sign artifacts.call BAPI',
                                        'ImageService/SignImage',
                                        MessageToJson(sample_response)),
      api.step_data(
          'sign artifacts.call BAPI.read cloudkms logs.list [CLEANUP]/signing-dir_tmp_2/cloudkms-logs',
          api.file.listdir([
              '[CLEANUP]/signing-dir_tmp_2/cloudkms-logs/log1',
              '[CLEANUP]/signing-dir_tmp_2/cloudkms-logs/log2',
          ])),
      api.step_data(
          'sign artifacts.call BAPI.read cloudkms logs.read log1',
          api.file.read_text('this is log 1'),
      ),
      api.step_data(
          'sign artifacts.call BAPI.read cloudkms logs.read log2',
          api.file.read_text('this is log 2'),
      ),
      api.post_check(post_process.LogContains, 'fetch signing config', 'branch',
                     ['Falling back to src_state.gitiles_commit']),
      api.post_check(
          post_process.MustRun,
          'sign artifacts.call BAPI.call chromite.api.ImageService/SignImage'),
      api.post_process(
          post_process.PropertyEquals, 'signed_upload_paths', {
              "canary-channel":
                  "gs://chromeos-throw-away-bucket/canary-channel/kukui/1234.56.0/"
          }), api.post_process(post_process.DropExpectation),
      build_target='kukui', builder='fwpackager-cq', status='FAILURE')
