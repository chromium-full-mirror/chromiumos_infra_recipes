# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for generating attestations for signed artifacts."""

from google.protobuf.json_format import MessageToDict, MessageToJson

from PB.chromite.api.image import SignImageResponse
from PB.chromiumos import build_report as build_report_pb2
from PB.chromiumos import signing as signing_pb2
from PB.chromiumos.common import (CHANNEL_CANARY, CHANNEL_DEV, IMAGE_TYPE_BASE,
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
  channels = [CHANNEL_DEV, CHANNEL_CANARY]

  for filepath in api.properties.get('files_to_mock', []):
    api.path.mock_add_file(filepath)

  # Call signing.
  api.signing.sign_artifacts(
      sign_types=sign_types, channels=channels,
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
                          signed_artifact_name='chromeos-firmwareupdate',
                      ),
                  ],
                  signing_status=PASSED,
              ),
          ]))

  yield api.build_menu.test(
      'no-bcid-steps', api.properties(attestation_eligible=False),
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
          post_process.DoesNotRun,
          'sign artifacts.copying local artifacts to prepare for signing.verify provenance for unsigned artifact.bcid_verifier: verify provenance'
      ),
      api.post_check(
          post_process.DoesNotRun,
          'sign artifacts.upload signed artifacts to chromeos-releases bucket.upload signed artifacts for CHANNEL_CANARY.generate signed provenance.Compute file hash'
      ),
      api.post_check(
          post_process.MustRun,
          'sign artifacts.upload signed artifacts to chromeos-releases bucket.upload signed artifacts for CHANNEL_CANARY.gsutil cp'
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
              'gs://chromeos-releases/canary-channel/kukui/1234.56.0/chromeos-firmwareupdate'
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
      ),
      api.post_check(
          post_process.MustRun,
          'sign artifacts.upload signed artifacts to chromeos-releases bucket.upload signed artifacts for CHANNEL_CANARY.gsutil cp'
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

  # This test verifies that all BCID failures are ignored by default, if no BCID
  # properties are passed in. Even if both verification of unsigned provenance
  # and generation of signed provenance fail, the build succeeds.
  yield api.build_menu.test(
      'all-bcid-checks-non-fatal',
      api.properties(
          attestation_eligible=True,
          files_to_mock=[
              '[CLEANUP]/signing-dir_tmp_1/recovery_image.tar.xz.intoto.jsonl'
          ],
      ),
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
      api.override_step_data(
          'sign artifacts.verify provenance for unsigned artifacts.verifying provenance for recovery_image.tar.xz.bcid_verifier: verify provenance',
          retcode=1),
      api.override_step_data(
          'sign artifacts.upload signed artifacts to chromeos-releases bucket.upload signed artifacts for CHANNEL_CANARY.generate signed provenance.Compute file hash',
          retcode=1),
      api.post_check(
          post_process.MustRun,
          'sign artifacts.upload signed artifacts to chromeos-releases bucket.upload signed artifacts for CHANNEL_CANARY.gsutil cp'
      ), api.post_process(post_process.DropExpectation), build_target='kukui',
      builder='kukui-release-main', status='SUCCESS')

  yield api.build_menu.test(
      'fatal-failure-unsigned-provenance-verification-no-upload',
      api.properties(
          attestation_eligible=True,
          files_to_mock=[
              '[CLEANUP]/signing-dir_tmp_1/recovery_image.tar.xz.intoto.jsonl',
              '[CLEANUP]/signing-dir_tmp_1/firmware_from_source.tar.bz2',
              '[CLEANUP]/signing-dir_tmp_1/chromiumos_base_image.tar.xz',
          ],
      ),
      api.properties(
          **{
              '$chromeos/signing':
                  MessageToDict(
                      SigningProperties(
                          local_signing=True,
                          gs_upload_bucket='chromeos-releases',
                          bcid_enforcement={
                              'unsigned_provenance_verification_fatal': True
                          })),
          }),
      api.post_check(
          post_process.MustRun,
          'sign artifacts.download release artifacts.gsutil download recovery_image.tar.xz from chromeos-releases-test/kukui-release-main/R99-1234.56.0-101-8945511751514863184'
      ),
      api.override_step_data(
          'sign artifacts.verify provenance for unsigned artifacts.verifying provenance for recovery_image.tar.xz.bcid_verifier: verify provenance',
          retcode=1),
      api.post_check(
          post_process.DoesNotRun,
          'sign artifacts.upload signed artifacts to chromeos-releases bucket.upload signed artifacts for CHANNEL_CANARY'
      ),
      api.post_check(
          post_process.DoesNotRun,
          'sign artifacts.upload signed artifacts to chromeos-releases bucket.upload signed artifacts for CHANNEL_CANARY.generate signed provenance'
      ),
      api.post_check(
          post_process.DoesNotRun,
          'sign artifacts.upload signed artifacts to chromeos-releases bucket.upload signed artifacts for CHANNEL_CANARY.generate signed provenance.snoop: report_gcs'
      ), api.post_process(post_process.DropExpectation), build_target='kukui',
      builder='kukui-release-main', status='FAILURE')

  yield api.build_menu.test(
      'try-download-attestation-file',
      api.properties(attestation_eligible=True),
      api.properties(
          **{
              '$chromeos/signing':
                  MessageToDict(
                      SigningProperties(
                          local_signing=True,
                          gs_upload_bucket='chromeos-releases',
                          bcid_enforcement={
                              'unsigned_provenance_verification_fatal': True
                          })),
          }),
      api.override_step_data(
          'sign artifacts.download release artifacts.gsutil download stateful.tgz.intoto.jsonl from chromeos-releases-test/kukui-release-main/R99-1234.56.0-101-8945511751514863184',
          retcode=1), api.post_process(post_process.DropExpectation),
      build_target='kukui', builder='kukui-release-main', status='SUCCESS')
