# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for generating attestations for signed artifacts."""

from google.protobuf.json_format import MessageToDict, MessageToJson

from PB.chromite.api.image import SignImageResponse
from PB.chromiumos import build_report as build_report_pb2
from PB.chromiumos import signing as signing_pb2
from PB.chromiumos.common import (CHANNEL_CANARY, IMAGE_TYPE_BASE,
                                  IMAGE_TYPE_RECOVERY, IMAGE_TYPE_FIRMWARE)
from PB.recipe_modules.chromeos.signing.signing import SigningProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'build_menu',
    'cros_build_api',
    'cros_infra_config',
    'signing',
]

PASSED = build_report_pb2.BuildReport.SignedBuildMetadata.SIGNING_STATUS_PASSED


def RunSteps(api: RecipeApi):
  sign_types = [IMAGE_TYPE_BASE, IMAGE_TYPE_FIRMWARE, IMAGE_TYPE_RECOVERY]
  channels = [CHANNEL_CANARY]

  # Call signing.
  api.signing.sign_artifacts(
      sign_types=sign_types, channels=channels,
      local_artifact_dir=api.path.start_dir / 'shellball-dir',
      attestation_eligible=api.properties['attestation_eligible'])


def GenTests(api: RecipeTestApi):
  sample_response = SignImageResponse(
      output_archive_dir='/archive_dir/',
      signed_artifacts=signing_pb2.BuildTargetSignedArtifacts(
          archive_artifacts=[
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
          ]))

  yield api.build_menu.test(
      'no-signed-attestations', api.properties(attestation_eligible=False),
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
      api.post_check(
          post_process.MustRun,
          'sign artifacts.upload signed artifacts to chromeos-releases bucket.upload signed artifacts for CHANNEL_CANARY'
      ),
      api.post_check(
          post_process.DoesNotRun,
          'sign artifacts.upload signed artifacts to chromeos-releases bucket.upload signed artifacts for CHANNEL_CANARY.generate signed provenance'
      ), api.post_process(post_process.DropExpectation), build_target='kukui',
      builder='kukui-release-main', status='SUCCESS')

  yield api.build_menu.test(
      'signed-attestations', api.properties(attestation_eligible=True),
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
      api.post_check(
          post_process.MustRun,
          'sign artifacts.upload signed artifacts to chromeos-releases bucket.upload signed artifacts for CHANNEL_CANARY'
      ),
      api.post_check(
          post_process.MustRun,
          'sign artifacts.upload signed artifacts to chromeos-releases bucket.upload signed artifacts for CHANNEL_CANARY.generate signed provenance'
      ),
      api.post_check(
          post_process.MustRun,
          'sign artifacts.upload signed artifacts to chromeos-releases bucket.upload signed artifacts for CHANNEL_CANARY.generate signed provenance.Compute file hash'
      ),
      api.post_check(
          post_process.StepCommandContains,
          'sign artifacts.upload signed artifacts to chromeos-releases bucket.upload signed artifacts for CHANNEL_CANARY.generate signed provenance.snoop: report_gcs',
          [
              '-report-gcs', '-digest', 'deadbeef', '-gcs-uri',
              'gs://chromeos-releases/canary-channel/kukui/1234.56.0//bar.bin'
          ]), api.post_process(post_process.DropExpectation),
      build_target='kukui', builder='kukui-release-main', status='SUCCESS')

  yield api.build_menu.test(
      'non-fatal-failure-signed-provenance-generation',
      api.properties(attestation_eligible=True),
      api.properties(
          **{
              '$chromeos/signing':
                  MessageToDict(
                      SigningProperties(local_signing=True,
                                        gs_upload_bucket='chromeos-releases')),
          }),
      api.cros_build_api.set_api_return('sign artifacts.call BAPI',
                                        'ImageService/SignImage',
                                        MessageToJson(sample_response)),
      api.post_check(
          post_process.MustRun,
          'sign artifacts.upload signed artifacts to chromeos-releases bucket.upload signed artifacts for CHANNEL_CANARY'
      ),
      api.post_check(
          post_process.MustRun,
          'sign artifacts.upload signed artifacts to chromeos-releases bucket.upload signed artifacts for CHANNEL_CANARY.generate signed provenance'
      ),
      api.override_step_data(
          'sign artifacts.upload signed artifacts to chromeos-releases bucket.upload signed artifacts for CHANNEL_CANARY.generate signed provenance.Compute file hash',
          retcode=1),
      api.post_check(
          post_process.DoesNotRun,
          'sign artifacts.upload signed artifacts to chromeos-releases bucket.upload signed artifacts for CHANNEL_CANARY.generate signed provenance.snoop: report_gcs'
      ), api.post_process(post_process.DropExpectation), build_target='kukui',
      builder='kukui-release-main', status='SUCCESS')

  yield api.build_menu.test(
      'fatal-failure-signed-provenance-generation',
      api.properties(attestation_eligible=True),
      api.properties(
          **{
              '$chromeos/signing':
                  MessageToDict(
                      SigningProperties(
                          local_signing=True,
                          gs_upload_bucket='chromeos-releases',
                          bcid_enforcement={
                              'signed_provenance_generation_fatal': True
                          })),
          }),
      api.cros_build_api.set_api_return('sign artifacts.call BAPI',
                                        'ImageService/SignImage',
                                        MessageToJson(sample_response)),
      api.post_check(
          post_process.MustRun,
          'sign artifacts.upload signed artifacts to chromeos-releases bucket.upload signed artifacts for CHANNEL_CANARY'
      ),
      api.post_check(
          post_process.MustRun,
          'sign artifacts.upload signed artifacts to chromeos-releases bucket.upload signed artifacts for CHANNEL_CANARY.generate signed provenance'
      ),
      api.override_step_data(
          'sign artifacts.upload signed artifacts to chromeos-releases bucket.upload signed artifacts for CHANNEL_CANARY.generate signed provenance.Compute file hash',
          retcode=1),
      api.post_check(
          post_process.DoesNotRun,
          'sign artifacts.upload signed artifacts to chromeos-releases bucket.upload signed artifacts for CHANNEL_CANARY.generate signed provenance.snoop: report_gcs'
      ), api.post_process(post_process.DropExpectation), build_target='kukui',
      builder='kukui-release-main', status='INFRA_FAILURE')
