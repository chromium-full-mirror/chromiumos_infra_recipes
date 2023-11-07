# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for sign_artifacts."""

from google.protobuf.json_format import MessageToDict, MessageToJson

from PB.chromite.api.image import SignImageResponse
from PB.chromiumos import signing as signing_pb2  # pylint: disable=unused-import
from PB.chromiumos.common import (CHANNEL_CANARY, CHANNEL_DEV, IMAGE_TYPE_BASE,
                                  IMAGE_TYPE_FACTORY, IMAGE_TYPE_RECOVERY,
                                  IMAGE_TYPE_FIRMWARE)
from PB.chromiumos.signing import BuildTargetSigningConfig, SigningConfig
from PB.recipe_modules.chromeos.signing.signing import SigningProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/properties',
    'build_menu',
    'cros_build_api',
    'signing',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'


def RunSteps(api: RecipeApi):
  # Fetch config.
  config = api.signing.get_config()
  expected_config = BuildTargetSigningConfig(
      build_target='kukui',
      signing_configs=[
          SigningConfig(
              image_type=IMAGE_TYPE_BASE,
              keyset='kukui-foo-bar',
              ensure_no_password=True,
              firmware_update=True,
          ),
          SigningConfig(
              image_type=IMAGE_TYPE_FACTORY,
              keyset='kukui-foo-bar',
              ensure_no_password=True,
              firmware_update=True,
          ),
          SigningConfig(
              image_type=IMAGE_TYPE_FIRMWARE,
              keyset='kukui-foo-bar',
              ensure_no_password=True,
              firmware_update=True,
          ),
          SigningConfig(
              image_type=IMAGE_TYPE_RECOVERY,
              keyset='kukui-foo-bar',
              ensure_no_password=True,
              firmware_update=True,
          ),
      ],
  )
  api.assertions.assertEqual(config, expected_config)

  sign_types = [IMAGE_TYPE_BASE, IMAGE_TYPE_FIRMWARE, IMAGE_TYPE_RECOVERY]
  channels = [CHANNEL_CANARY, CHANNEL_DEV]

  processed_config, _ = api.signing.setup_signing(sign_types, channels)
  expected_processed_config = BuildTargetSigningConfig(
      build_target='kukui',
      signing_configs=[
          SigningConfig(
              image_type=IMAGE_TYPE_BASE,
              channel=CHANNEL_CANARY,
              version='1234.56.0',
              keyset='kukui-foo-bar',
              ensure_no_password=True,
              firmware_update=True,
              archive_path='chromiumos_base_image.tar.xz',
          ),
          SigningConfig(
              image_type=IMAGE_TYPE_FIRMWARE,
              channel=CHANNEL_CANARY,
              version='1234.56.0',
              keyset='kukui-foo-bar',
              ensure_no_password=True,
              firmware_update=True,
              archive_path='firmware_from_source.tar.bz2',
          ),
          SigningConfig(
              image_type=IMAGE_TYPE_RECOVERY,
              channel=CHANNEL_CANARY,
              version='1234.56.0',
              keyset='kukui-foo-bar',
              ensure_no_password=True,
              firmware_update=True,
              archive_path='recovery_image.tar.xz',
          ),
          SigningConfig(
              image_type=IMAGE_TYPE_BASE,
              channel=CHANNEL_DEV,
              version='1234.56.0',
              keyset='kukui-foo-bar',
              ensure_no_password=True,
              firmware_update=True,
              archive_path='chromiumos_base_image.tar.xz',
          ),
          SigningConfig(
              image_type=IMAGE_TYPE_FIRMWARE,
              channel=CHANNEL_DEV,
              version='1234.56.0',
              keyset='kukui-foo-bar',
              ensure_no_password=True,
              firmware_update=True,
              archive_path='firmware_from_source.tar.bz2',
          ),
          SigningConfig(
              image_type=IMAGE_TYPE_RECOVERY,
              channel=CHANNEL_DEV,
              version='1234.56.0',
              keyset='kukui-foo-bar',
              ensure_no_password=True,
              firmware_update=True,
              archive_path='recovery_image.tar.xz',
          ),
      ],
  )
  api.assertions.assertEqual(processed_config, expected_processed_config)

  # Call signing.
  api.signing.sign_artifacts(sign_types, channels)


def GenTests(api: RecipeTestApi):
  sample_response = SignImageResponse(
      output_archive_dir='/archive_dir/',
      signed_artifacts=signing_pb2
      .BuildTargetSignedArtifacts(archive_artifacts=[
          signing_pb2.ArchiveArtifacts(
              build_target='kukui', channel=CHANNEL_DEV, signed_artifacts=[
                  signing_pb2.SignedArtifact(
                      status=signing_pb2.STATUS_SUCCESS,
                      signed_artifact_name='foo.bin',
                  ),
                  signing_pb2.SignedArtifact(
                      status=signing_pb2.STATUS_FAILURE,
                      signed_artifact_name='bad-artifact',
                  )
              ]),
          signing_pb2.ArchiveArtifacts(
              build_target='kukui', channel=CHANNEL_CANARY, signed_artifacts=[
                  signing_pb2.SignedArtifact(
                      status=signing_pb2.STATUS_SUCCESS,
                      signed_artifact_name='bar.bin',
                  ),
              ]),
          signing_pb2.ArchiveArtifacts(
              build_target='kukui',
              # no channel, gets skipped.
              signed_artifacts=[
                  signing_pb2.SignedArtifact(
                      status=signing_pb2.STATUS_SUCCESS,
                      signed_artifact_name='no-channel.bin',
                  ),
              ])
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
      api.cros_build_api.set_api_return('sign artifacts',
                                        'ImageService/SignImage',
                                        MessageToJson(sample_response)),
      api.post_check(
          post_process.StepCommandContains,
          'sign artifacts.upload unsigned artifacts to chromeos-releases bucket.upload unsigned artifacts for CHANNEL_DEV.gsutil cp',
          [
              'gs://chromeos-releases/dev-channel/kukui/1234.56.0/ChromeOS-base-R99-1234.56.0-kukui.tar.xz',
          ]),
      api.post_check(
          post_process.StepCommandContains,
          'sign artifacts.upload unsigned artifacts to chromeos-releases bucket.upload unsigned artifacts for CHANNEL_DEV.gsutil cp (2)',
          [
              'gs://chromeos-releases/dev-channel/kukui/1234.56.0/ChromeOS-firmware-R99-1234.56.0-kukui.tar.bz2',
          ]),
      api.post_check(
          post_process.StepCommandContains,
          'sign artifacts.upload unsigned artifacts to chromeos-releases bucket.upload unsigned artifacts for CHANNEL_DEV.gsutil cp (3)',
          [
              'gs://chromeos-releases/dev-channel/kukui/1234.56.0/ChromeOS-recovery-R99-1234.56.0-kukui.tar.xz',
          ]),
      api.post_check(
          post_process.StepCommandContains,
          'sign artifacts.upload unsigned artifacts to chromeos-releases bucket.upload unsigned artifacts for CHANNEL_DEV.gsutil cp (7)',
          [
              'gs://chromeos-releases/dev-channel/kukui/1234.56.0/ChromeOS-R99-1234.56.0-kukui.zip',
          ]),
      api.post_check(
          post_process.StepCommandContains,
          'sign artifacts.upload unsigned artifacts to chromeos-releases bucket.upload unsigned artifacts for CHANNEL_DEV.gsutil cp (8)',
          [
              'gs://chromeos-releases/dev-channel/kukui/1234.56.0/debug-kukui.tgz',
          ]),
      api.post_check(
          post_process.StepCommandContains,
          'sign artifacts.upload unsigned artifacts to chromeos-releases bucket.upload unsigned artifacts for CHANNEL_DEV.gsutil cp (9)',
          [
              'gs://chromeos-releases/dev-channel/kukui/1234.56.0/ChromeOS-test-R99-1234.56.0-kukui.tar.xz',
          ]),
      api.post_check(post_process.MustRun,
                     'sign artifacts.call chromite.api.ImageService/SignImage'),
      api.post_check(
          post_process.DoesNotRun,
          'sign artifacts.upload signed artifacts to chromeos-releases bucket.upload signed artifacts for CHANNEL_UNSPECIFIED'
      ),
      api.post_check(
          post_process.StepCommandContains,
          'sign artifacts.upload signed artifacts to chromeos-releases bucket.upload signed artifacts for CHANNEL_DEV.gsutil cp',
          [
              '/archive_dir/foo.bin',
              'gs://chromeos-releases/dev-channel/kukui/1234.56.0/'
          ]),
      api.post_check(
          post_process.StepCommandContains,
          'sign artifacts.upload signed artifacts to chromeos-releases bucket.upload signed artifacts for CHANNEL_CANARY.gsutil cp',
          [
              '/archive_dir/bar.bin',
              'gs://chromeos-releases/canary-channel/kukui/1234.56.0/'
          ]), api.post_process(post_process.DropExpectation),
      build_target='kukui', builder='kukui-release-main', status='FAILURE')

  yield api.build_menu.test(
      'no-signed-artifacts',
      api.properties(
          **{
              '$chromeos/signing':
                  MessageToDict(
                      SigningProperties(local_signing=True,
                                        gs_upload_bucket='chromeos-releases'))
          }),
      api.cros_build_api.set_api_return('sign artifacts',
                                        'ImageService/SignImage', '{}'),
      api.post_check(
          post_process.StepCommandContains,
          'sign artifacts.upload unsigned artifacts to chromeos-releases bucket.upload unsigned artifacts for CHANNEL_DEV.gsutil cp',
          [
              'gs://chromeos-releases/dev-channel/kukui/1234.56.0/ChromeOS-base-R99-1234.56.0-kukui.tar.xz'
          ]),
      api.post_check(post_process.MustRun,
                     'sign artifacts.call chromite.api.ImageService/SignImage'),
      api.post_check(
          post_process.StepTextEquals,
          'sign artifacts.upload signed artifacts to chromeos-releases bucket',
          'no signed artifacts'),
      api.post_process(post_process.DropExpectation), build_target='kukui',
      builder='kukui-release-main')

  yield api.build_menu.test(
      'no-signing-config',
      api.properties(**{
          '$chromeos/signing':
              MessageToDict(SigningProperties(local_signing=True))
      }), api.post_process(post_process.DropExpectation), build_target='eve',
      builder='eve-release-main', status='FAILURE')

  yield api.test(
      'no-builder-config',
      api.post_check(post_process.StepFailure, 'fetch signing config'),
      api.post_process(post_process.DropExpectation),
      status='FAILURE',
  )

  yield api.build_menu.test(
      'signing-disabled',
      api.post_check(
          post_process.SummaryMarkdown,
          'Cannot sign artifacts when local signing is not configured'),
      api.post_process(post_process.DropExpectation), status='FAILURE',
      build_target='kukui', builder='kukui-release-main')
