# Copyright 2026 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tests for the firmware_config recipe module."""

from PB.chromite.api.firmware import FirmwareArtifactInfo
from recipe_engine import post_process
from RECIPE_MODULES.chromeos.cros_artifacts.api import UploadedArtifacts

DEPS = [
    'recipe_engine/buildbucket',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/time',
    'firmware_config',
]


def RunSteps(api):
  files_by_artifact = dict(
      api.properties.get(
          'files_by_artifact',
          {
              'FIRMWARE_TARBALL': [
                  'krabby.EC.16640.2.39.tar.bz2',
                  'grogu.16849.0.0.tar.bz2',
                  'atria/firmware_from_source.tar.bz2',
              ],
              'FIRMWARE_CONFIG': [
                  'configs/krabby/ec-ro.config',
                  'configs/krabby/ec-rw.config',
                  'configs/krabby/components.json',
                  'configs/grogu/coreboot.config',
                  'configs/README',
              ],
          },
      ))
  uploaded_artifacts = UploadedArtifacts(
      gs_bucket='chromeos-image-archive',
      gs_path='firmware-zephyr-postsubmit/R99-1234.56.0-1',
      files_by_artifact=files_by_artifact,
      published={},
  )
  metadata_by_name = {
      'krabby.EC.16640.2.39.tar.bz2':
          FirmwareArtifactInfo.TarballInfo(board=['corsola']),
  }
  api.firmware_config.publish(
      uploaded_artifacts,
      api.path.cleanup_dir / 'artifacts',
      metadata_by_name,
      api.time.utcnow(),
  )


def GenTests(api):
  yield api.test(
      'basic',
      api.buildbucket.ci_build(
          project='chromeos',
          bucket='postsubmit',
          builder='firmware-zephyr-postsubmit',
          git_repo='https://chrome-internal.googlesource.com/chromeos/manifest-internal',
          git_ref='refs/heads/snapshot',
          revision='a' * 40,
      ),
      api.post_process(post_process.MustRun,
                       'publish target configs.write rows'),
      api.post_process(
          post_process.LogContains,
          'publish target configs',
          'input',
          [
              '"database": "build_metadata"',
              '"platform": "corsola"',
              '"target": "krabby"',
              '"ec-ro": "[CLEANUP]/artifacts/configs/krabby/ec-ro.config"',
              '"ec-rw": "[CLEANUP]/artifacts/configs/krabby/ec-rw.config"',
              '"components_path": "[CLEANUP]/artifacts/configs/krabby/components.json"',
              '"coreboot": "[CLEANUP]/artifacts/configs/grogu/coreboot.config"',
          ],
      ),
  )

  yield api.test(
      'staging',
      api.buildbucket.ci_build(
          project='chromeos',
          bucket='staging',
          builder='staging-firmware-zephyr-postsubmit',
          git_repo='https://chrome-internal.googlesource.com/chromeos/manifest-internal',
          git_ref='refs/heads/snapshot',
          revision='a' * 40,
          experiments=['chromeos.cros_infra_config.staging'],
      ),
      api.post_process(
          post_process.LogContains,
          'publish target configs',
          'input',
          ['"database": "build_metadata_staging"'],
      ),
  )

  yield api.test(
      'empty',
      api.properties(files_by_artifact={}),
      api.post_process(post_process.DoesNotRun, 'publish target configs'),
  )
