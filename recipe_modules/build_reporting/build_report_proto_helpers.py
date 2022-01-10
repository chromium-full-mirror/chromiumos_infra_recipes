# -*- coding: utf-8 -*-
# Copyright 2022 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Various helper methods for creating/populating BuildReport instances."""

from recipe_engine.recipe_api import StepFailure
from PB.chromiumos.build_report import BuildReportBeta as BuildReport

BuildConfig = BuildReport.BuildConfig


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
    raise StepFailure("build_target_metadata must have a single element")
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
