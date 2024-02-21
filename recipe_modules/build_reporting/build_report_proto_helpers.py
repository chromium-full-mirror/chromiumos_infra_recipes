# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Various helper methods for creating/populating BuildReport instances."""
from recipe_engine.recipe_api import StepFailure
from PB.chromiumos.build_report import BuildReport
from PB.chromiumos.common import Channel, ImageType

BuildConfig = BuildReport.BuildConfig
SignedBuild = BuildReport.SignedBuildMetadata


def set_build_target_metadata(config, builder_metadata):
  """Populates a BuildConfig object with build target metadata.

  This operates in place on the BuildConfig.

  Args:
    config (BuildConfig): Config object to populate.
    builder_metadata (GetBuilderMetadataResponse): Builder metadata to read.
  """
  # While the proto supports multiple BuildTargetMetadata objects, both the
  # code responding with the proto and the object model assume there will be
  # one build target per build. As such, we are extracting that single item
  # from the list, throwing an exception if there is more than one item.
  if len(builder_metadata.build_target_metadata) != 1:
    raise StepFailure('build_target_metadata must have a single element')
  [build_target_metadata] = builder_metadata.build_target_metadata

  config.target.name = build_target_metadata.build_target
  config.android_container_target.name = build_target_metadata.android_container_target
  config.android_container_branch.name = build_target_metadata.android_container_branch
  config.arc_use_set = build_target_metadata.arc_use_set

  android_container_version = config.versions.add()
  android_container_version.kind = BuildConfig.VERSION_KIND_ANDROID_CONTAINER
  android_container_version.value = build_target_metadata.android_container_version

  ec_firmware_version = config.versions.add()
  ec_firmware_version.kind = BuildConfig.VERSION_KIND_EC_FIRMWARE
  ec_firmware_version.value = build_target_metadata.ec_firmware_version

  kernel_version = config.versions.add()
  kernel_version.kind = BuildConfig.VERSION_KIND_KERNEL
  kernel_version.value = build_target_metadata.kernel_version

  main_firmware_version = config.versions.add()
  main_firmware_version.kind = BuildConfig.VERSION_KIND_MAIN_FIRMWARE
  main_firmware_version.value = build_target_metadata.main_firmware_version

  for fingerprint in build_target_metadata.fingerprints:
    fingerprint_version = config.versions.add()
    fingerprint_version.kind = BuildConfig.VERSION_KIND_FINGERPRINT
    fingerprint_version.value = fingerprint


def create_model(model_metadata):
  """Creates a BuildConfig.Model given a ModelMetadata.

  Args:
    model_metadata (ModelMetadata): Model metadata to read.

  Returns:
    Model object.
  """
  model = BuildConfig.Model()
  model.name = model_metadata.model_name
  model.firmware_key_id = model_metadata.firmware_key_id

  ec_firmware_version = model.versions.add()
  ec_firmware_version.kind = BuildConfig.Model.MODEL_VERSION_KIND_EC_FIRMWARE
  ec_firmware_version.value = model_metadata.ec_firmware_version

  main_readwrite_firmware_version = model.versions.add()
  main_readwrite_firmware_version.kind = BuildConfig.Model.MODEL_VERSION_KIND_MAIN_READWRITE_FIRMWARE
  main_readwrite_firmware_version.value = model_metadata.main_readwrite_firmware_version

  main_readonly_firmware_version = model.versions.add()
  main_readonly_firmware_version.kind = BuildConfig.Model.MODEL_VERSION_KIND_MAIN_READONLY_FIRMWARE
  main_readonly_firmware_version.value = model_metadata.main_readonly_firmware_version

  return model


def create_signed_build(signed_build_meta, status):
  """Creates a SignedBuildMetadata object from the provided meta dict.

  Args:
    signed_build_meta (dict): The signed build metadata from the signers.
    status (str): The status of the signing job.

  Returns:
    Signed Build object.
  """
  signed_build = SignedBuild()

  signed_build.release_directory = signed_build_meta['release_directory']
  signed_build.status = SignedBuild.SigningStatus.Value(
      'SIGNING_STATUS_{}'.format(status.upper()))
  signed_build.board = signed_build_meta['board']
  # For now always assume that signed UEFI kernels are Flexor.
  # This may change in the future.
  image_type = 'FLEXOR_KERNEL' if signed_build_meta['type'].upper(
  ) == 'UEFI_KERNEL' else signed_build_meta['type'].upper()
  signed_build.type = ImageType.Value('IMAGE_TYPE_{}'.format(image_type))
  signed_build.channel = Channel.Value('CHANNEL_{}'.format(
      signed_build_meta['channel'].upper()))
  signed_build.keyset = signed_build_meta['keyset']
  signed_build.keyset_is_mp = signed_build_meta['keyset_is_mp']

  for filename, hashes in signed_build_meta['outputs'].items():
    file_with_hashes = signed_build.files.add()
    file_with_hashes.filename = filename
    file_with_hashes.md5 = hashes['md5']
    file_with_hashes.sha1 = hashes['sha1']
    file_with_hashes.sha256 = hashes['sha256']
    file_with_hashes.size = hashes['size']

  platform_version = signed_build.versions.add()
  platform_version.kind = SignedBuild.VersionKind.VERSION_KIND_PLATFORM
  platform_version.value = signed_build_meta['version']['platform']

  milestone_version = signed_build.versions.add()
  milestone_version.kind = SignedBuild.VersionKind.VERSION_KIND_MILESTONE
  milestone_version.value = signed_build_meta['version']['milestone']

  key_firmware_key_version = signed_build.versions.add()
  key_firmware_key_version.kind = SignedBuild.VersionKind.VERSION_KIND_KEY_FIRMWARE_KEY
  key_firmware_key_version.value = str(
      signed_build_meta['key_versions']['firmware_key_version'])

  key_firmware_version = signed_build.versions.add()
  key_firmware_version.kind = SignedBuild.VersionKind.VERSION_KIND_KEY_FIRMWARE
  key_firmware_version.value = str(
      signed_build_meta['key_versions']['firmware_version'])

  key_kernel_key_version = signed_build.versions.add()
  key_kernel_key_version.kind = SignedBuild.VersionKind.VERSION_KIND_KEY_KERNEL_KEY
  key_kernel_key_version.value = str(
      signed_build_meta['key_versions']['kernel_key_version'])

  key_kernel_version = signed_build.versions.add()
  key_kernel_version.kind = SignedBuild.VersionKind.VERSION_KIND_KEY_KERNEL
  key_kernel_version.value = str(
      signed_build_meta['key_versions']['kernel_version'])

  return signed_build
