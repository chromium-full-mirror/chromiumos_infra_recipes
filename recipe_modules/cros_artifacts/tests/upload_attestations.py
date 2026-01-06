# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for generating BCID attestations for artifacts."""

import json

from google.protobuf.json_format import MessageToDict

from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos import common
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import BuildTarget
from PB.recipe_modules.chromeos.cros_artifacts.cros_artifacts import CrosArtifactsProperties
from PB.recipe_modules.chromeos.cros_artifacts.tests.upload_attestations import \
    UploadAttestationsProperties
from recipe_engine import post_process
from RECIPE_MODULES.chromeos.cros_ssci.api import UploadedSBOM

PROPERTIES = UploadAttestationsProperties

DEPS = [
    'recipe_engine/assertions',
    'recipe_engine/file',
    'recipe_engine/properties',
    'recipe_engine/buildbucket',
    'cros_artifacts',
    'cros_build_api',
    'cros_ssci',
]



def RunSteps(api, properties):
  artifacts_info = common.ArtifactsByService(
      legacy=common.ArtifactsByService.Legacy(output_artifacts=[
          common.ArtifactsByService.Legacy.ArtifactInfo(artifact_types=[
              common.ArtifactsByService.Legacy.IMAGE_ARCHIVES,
          ])
      ]),
      toolchain=common.ArtifactsByService.Toolchain(output_artifacts=[
          common.ArtifactsByService.Toolchain.ArtifactInfo(
              artifact_types=[
                  common.ArtifactsByService.Toolchain
                  .UNVERIFIED_CHROME_BENCHMARK_AFDO_FILE
              ], gs_locations=['publish_gs_location', 'pub2/{gs_path}'],
              acl_name='public-read')
      ]),
      firmware=common.ArtifactsByService.Firmware(output_artifacts=[
          common.ArtifactsByService.Firmware.ArtifactInfo(
              artifact_types=[
                  common.ArtifactsByService.Firmware.FIRMWARE_TARBALL,
                  common.ArtifactsByService.Firmware.FIRMWARE_TARBALL_INFO,
                  common.ArtifactsByService.Firmware.FIRMWARE_LCOV,
                  common.ArtifactsByService.Firmware.CODE_COVERAGE_HTML,
              ], acl_name='public-read')
      ]),
      sysroot=common.ArtifactsByService.Sysroot(output_artifacts=[
          common.ArtifactsByService.Sysroot.ArtifactInfo(
              artifact_types=[
                  common.ArtifactsByService.Sysroot.DEBUG_SYMBOLS,
                  common.ArtifactsByService.Sysroot.BREAKPAD_DEBUG_SYMBOLS,
              ], acl_name='public-read')
      ]),
      infra=common.ArtifactsByService.Infra(output_artifacts=[
          common.ArtifactsByService.Infra.ArtifactInfo(artifact_types=[
              common.ArtifactsByService.Infra.BUILD_MANIFEST,
          ])
      ]),
  )

  if properties.exclude_image_archives:
    artifacts_info.legacy.Clear()

  api.cros_artifacts.upload_artifacts(
      'builder', BuilderConfig.Id.Type.RELEASE, 'test-bucket',
      artifacts_info=artifacts_info,
      sysroot=Sysroot(path='/build/target',
                      build_target=BuildTarget(name='target')),
      report_to_spike=True, attestation_eligible=True, artifact_sbom={
          'chromiumos_base_image.tar.xz':
              UploadedSBOM(digest="decacafe", gs_url="gs://bucket/spdx.json"),
      }, ignore_breakpad_symbol_generation_errors=properties
      .ignore_breakpad_symbol_generation_errors)


def GenTests(api):

  yield api.test(
      'basic',
      api.cros_build_api.set_api_return(
          'upload artifacts.bundle IMAGE_ARCHIVES for upload',
          'ArtifactsService/BundleImageArchives',
          json.dumps(
              {
                  'artifacts': [{
                      'path':
                          '[CLEANUP]/artifacts_tmp_1/chromiumos_base_image.tar.xz',
                  }],
              }, sort_keys=True)),
      api.cros_build_api.set_api_return(
          'upload artifacts', 'FirmwareService/BundleFirmwareArtifacts',
          json.dumps(
              {
                  'artifacts': {
                      'artifacts': [{
                          'paths': [{
                              'path':
                                  '[CLEANUP]/artifacts_tmp_1/firmware_from_source.tar.bz2'
                          }],
                      }],
                  },
              }, sort_keys=True)),
      api.post_process(
          post_process.MustRun,
          'upload artifacts.generate provenance.report sbom for chromiumos_base_image.tar.xz.snoop: report_sbom'
      ),
      api.post_process(
          post_process.MustRun,
          'upload artifacts.generate provenance.snoop: report_gcs'),
  ) + api.buildbucket.ci_build(project="chromeos", builder="amd64")

  yield api.test(
      'ignore-breakpad-symbol-generation-errors',
      api.properties(ignore_breakpad_symbol_generation_errors=True),
      api.cros_build_api.set_api_return(
          'upload artifacts.bundle IMAGE_ARCHIVES for upload',
          'ArtifactsService/BundleImageArchives',
          json.dumps(
              {
                  'artifacts': [{
                      'path':
                          '[CLEANUP]/artifacts_tmp_1/chromiumos_base_image.tar.xz',
                  }],
              }, sort_keys=True)),
      api.post_process(
          post_process.MustRun,
          'upload artifacts.generate provenance.snoop: report_gcs'),
  ) + api.buildbucket.ci_build(project="chromeos", builder="amd64")

  yield api.test(
      'firmware-tarball-requires-provenance',
      api.cros_build_api.set_api_return(
          'upload artifacts.bundle IMAGE_ARCHIVES for upload',
          'ArtifactsService/BundleImageArchives',
          json.dumps(
              {
                  'artifacts': [{
                      'path':
                          '[CLEANUP]/artifacts_tmp_1/chromiumos_base_image.tar.xz',
                  }],
              }, sort_keys=True)),
      api.cros_build_api.set_api_return(
          'upload artifacts', 'FirmwareService/BundleFirmwareArtifacts',
          json.dumps(
              {
                  'artifacts': {
                      'artifacts': [{
                          'artifact_type':
                              'FIRMWARE_TARBALL',
                          'paths': [{
                              'path':
                                  '[CLEANUP]/artifacts_tmp_1/firmware_from_source.tar.bz2'
                          }],
                      }],
                  },
              }, sort_keys=True)),
      api.properties(
          **{
              '$chromeos/cros_artifacts':
                  MessageToDict(
                      CrosArtifactsProperties(bcid_enforcement={
                          'upload_artifact_prov_generation_fatal': True,
                      })),
          }),
      api.post_process(
          post_process.MustRun,
          'upload artifacts.generate provenance.snoop: report_gcs'),
      api.post_process(
          post_process.StepCommandContains,
          'upload artifacts.generate provenance.snoop: report_gcs', [
              "gs://test-bucket/builder/R99-1234.56.0-101-8945511751514863184/chromiumos_base_image.tar.xz"
          ]),
      api.post_process(
          post_process.MustRun,
          'upload artifacts.generate provenance.snoop: report_gcs (2)'),
      api.post_process(
          post_process.StepCommandContains,
          'upload artifacts.generate provenance.snoop: report_gcs (2)', [
              "gs://test-bucket/builder/R99-1234.56.0-101-8945511751514863184/firmware_from_source.tar.bz2"
          ]),
      api.post_process(post_process.DropExpectation),
  ) + api.buildbucket.ci_build(project="chromeos", builder="amd64")

  yield api.test(
      'firmware-tarball-requires-provenance-target-in-outpath',
      api.cros_build_api.set_api_return(
          'upload artifacts.bundle IMAGE_ARCHIVES for upload',
          'ArtifactsService/BundleImageArchives',
          json.dumps(
              {
                  'artifacts': [{
                      'path':
                          '[CLEANUP]/artifacts_tmp_1/chromiumos_base_image.tar.xz',
                  }],
              }, sort_keys=True)),
      api.cros_build_api.set_api_return(
          'upload artifacts', 'FirmwareService/BundleFirmwareArtifacts',
          json.dumps(
              {
                  'artifacts': {
                      'artifacts': [{
                          'artifact_type':
                              'FIRMWARE_TARBALL',
                          'paths': [{
                              'path':
                                  '[CLEANUP]/artifacts_tmp_1/target/firmware_from_source.tar.bz2'
                          }],
                      }],
                  },
              }, sort_keys=True)),
      api.properties(
          **{
              '$chromeos/cros_artifacts':
                  MessageToDict(
                      CrosArtifactsProperties(bcid_enforcement={
                          'upload_artifact_prov_generation_fatal': True,
                      })),
          }),
      api.post_process(
          post_process.MustRun,
          'upload artifacts.generate provenance.snoop: report_gcs'),
      api.post_process(
          post_process.StepCommandContains,
          'upload artifacts.generate provenance.snoop: report_gcs', [
              "gs://test-bucket/builder/R99-1234.56.0-101-8945511751514863184/chromiumos_base_image.tar.xz"
          ]),
      api.post_process(
          post_process.MustRun,
          'upload artifacts.generate provenance.snoop: report_gcs (2)'),
      api.post_process(
          post_process.StepCommandContains,
          'upload artifacts.generate provenance.Compute file hash (2)', [
              "vpython3", "-u",
              "RECIPE_MODULE[recipe_engine::file]/resources/fileutil.py",
              "--json-output", "/path/to/tmp/json", "file_hash",
              "[CLEANUP]/artifacts_tmp_1/target/firmware_from_source.tar.bz2"
          ]),
      api.post_process(
          post_process.StepCommandContains,
          'upload artifacts.generate provenance.snoop: report_gcs (2)', [
              "gs://test-bucket/builder/R99-1234.56.0-101-8945511751514863184/target/firmware_from_source.tar.bz2"
          ]),
  ) + api.buildbucket.ci_build(project="chromeos", builder="amd64")

  yield api.test(
      'image-archives-does-not-exist',
      api.properties(exclude_image_archives=True),
      api.cros_build_api.set_api_return(
          'upload artifacts', 'FirmwareService/BundleFirmwareArtifacts',
          json.dumps(
              {
                  'artifacts': {
                      'artifacts': [{
                          'artifact_type':
                              'FIRMWARE_TARBALL',
                          'paths': [{
                              'path':
                                  '[CLEANUP]/artifacts_tmp_1/firmware_from_source.tar.bz2'
                          }],
                      }],
                  },
              }, sort_keys=True)),
      api.post_process(
          post_process.StepCommandContains,
          'upload artifacts.generate provenance.snoop: report_gcs', [
              "gs://test-bucket/builder/R99-1234.56.0-101-8945511751514863184/firmware_from_source.tar.bz2"
          ]),
      api.post_process(
          post_process.LogContains, 'upload artifacts', 'report_to_spike',
          ['type IMAGE_ARCHIVES did not have any matching files.']),
  ) + api.buildbucket.ci_build(project="chromeos", builder="amd64")

  yield api.test(
      'local-dlcs-with-failure-and-retry',
      api.cros_build_api.set_api_return(
          'upload artifacts.bundle IMAGE_ARCHIVES for upload',
          'ArtifactsService/BundleImageArchives',
          json.dumps(
              {
                  'artifacts': [{
                      'path':
                          '[CLEANUP]/artifacts_tmp_1/chromiumos_base_image.tar.xz',
                  }],
              }, sort_keys=True)),
      api.cros_build_api.set_api_return(
          'upload artifacts', 'FirmwareService/BundleFirmwareArtifacts',
          json.dumps(
              {
                  'artifacts': {
                      'artifacts': [{
                          'artifact_type':
                              'FIRMWARE_TARBALL',
                          'paths': [{
                              'path':
                                  '[CLEANUP]/artifacts_tmp_1/firmware_from_source.tar.bz2'
                          }],
                      }],
                  },
              }, sort_keys=True)),
      api.step_data(
          'upload artifacts.Find DLCs.list local DLCs',
          api.file.listdir(['fake/dlc.img', 'fake2/dlc.img', 'fake3/dlc.img']),
      ),
      api.post_check(post_process.MustRun,
                     'upload artifacts.Find DLCs.list local DLCs'),
      # First artifact which succeeds on report
      api.post_process(
          post_process.MustRun,
          'upload artifacts.generate provenance.snoop: report_gcs'),
      api.post_process(
          post_process.StepCommandContains,
          'upload artifacts.generate provenance.snoop: report_gcs', [
              "gs://test-bucket/builder/R99-1234.56.0-101-8945511751514863184/chromiumos_base_image.tar.xz"
          ]),
      api.post_process(
          post_process.StepCommandContains,
          'upload artifacts.generate provenance.snoop: report_gcs (2)', [
              "gs://test-bucket/builder/R99-1234.56.0-101-8945511751514863184/firmware_from_source.tar.bz2"
          ]),
      # First DLC fails
      api.override_step_data(
          'upload artifacts.generate provenance.snoop: report_gcs (3)',
          retcode=1),
      api.override_step_data(
          'upload artifacts.generate provenance.snoop: report_gcs (4)',
          retcode=1),
      api.override_step_data(
          'upload artifacts.generate provenance.snoop: report_gcs (5)',
          retcode=1),
      api.override_step_data(
          'upload artifacts.generate provenance.snoop: report_gcs (6)',
          retcode=1),
      api.post_process(
          post_process.StepCommandContains,
          'upload artifacts.generate provenance.snoop: report_gcs (6)', [
              "gs://test-bucket/builder/R99-1234.56.0-101-8945511751514863184/dlc/fake/dlc.img"
          ]),
      # Give up on DLC 1 and move onto DLC 2 & 3.
      api.post_process(
          post_process.StepCommandContains,
          'upload artifacts.generate provenance.snoop: report_gcs (7)', [
              "gs://test-bucket/builder/R99-1234.56.0-101-8945511751514863184/dlc/fake2/dlc.img"
          ]),
      api.post_process(
          post_process.StepCommandContains,
          'upload artifacts.generate provenance.snoop: report_gcs (8)', [
              "gs://test-bucket/builder/R99-1234.56.0-101-8945511751514863184/dlc/fake3/dlc.img"
          ]),
      # DLC SBOMs were generated and reported.
      api.post_process(
          post_process.MustRun,
          'upload artifacts.generate provenance.generate and report sbom for dlc: fake'
      ),
      api.post_process(
          post_process.StepCommandContains,
          'upload artifacts.generate provenance.generate and report sbom for dlc: fake.snoop: report_sbom',
          [
              'gs://test-bucket/builder/R99-1234.56.0-101-8945511751514863184/dlc/fake/dlc.img.spdx.json'
          ]),
      status='SUCCESS') + api.buildbucket.ci_build(project="chromeos",
                                                   builder="amd64")

  yield api.test(
      'provenance-failure-with-enforcement',
      api.properties(
          **{
              '$chromeos/cros_artifacts':
                  MessageToDict(
                      CrosArtifactsProperties(bcid_enforcement={
                          'upload_artifact_prov_generation_fatal': True
                      })),
          }),
      api.step_data(
          'upload artifacts.Find DLCs.list local DLCs',
          api.file.listdir([
              'fake/dlc.img', 'fake2/dlc.img', 'fake3/dlc.img', 'fake4/dlc.img'
          ]),
      ),
      # We do 3 retries, and all 3 must fail in order for the step to fail.
      api.step_data(
          'upload artifacts.generate provenance.snoop: report_gcs',
          retcode=1,
      ),
      api.step_data(
          'upload artifacts.generate provenance.snoop: report_gcs (2)',
          retcode=1,
      ),
      api.step_data(
          'upload artifacts.generate provenance.snoop: report_gcs (3)',
          retcode=1,
      ),
      api.step_data(
          'upload artifacts.generate provenance.snoop: report_gcs (4)',
          retcode=1,
      ),
      api.post_process(post_process.DropExpectation),
      status='FAILURE') + api.buildbucket.ci_build(project="chromeos",
                                                   builder="amd64")
