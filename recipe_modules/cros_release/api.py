# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""An API for providing release related operations (e.g. paygen, signing)."""

from recipe_engine import recipe_api
from recipe_engine.recipe_api import StepFailure

from PB.chromite.api.sysroot import Sysroot
from PB.chromiumos.common import (Channel, IMAGE_TYPE_RECOVERY,
                                  IMAGE_TYPE_FACTORY, IMAGE_TYPE_FIRMWARE,
                                  IMAGE_TYPE_ACCESSORY_USBPD,
                                  IMAGE_TYPE_ACCESSORY_RWSIG, IMAGE_TYPE_BASE,
                                  IMAGE_TYPE_GSC_FIRMWARE)


class CrosReleaseApi(recipe_api.RecipeApi):

  @property
  def _supported_sign_types(self):
    """Supported image types for signing.

    These are kept in sync with chromite/scripts/pushimage.py.

    Returns:
      A set of image type enum values.
    """
    return set([
        IMAGE_TYPE_RECOVERY, IMAGE_TYPE_FACTORY, IMAGE_TYPE_FIRMWARE,
        IMAGE_TYPE_ACCESSORY_USBPD, IMAGE_TYPE_ACCESSORY_RWSIG, IMAGE_TYPE_BASE,
        IMAGE_TYPE_GSC_FIRMWARE
    ])

  def _validate_sign_types(self, sign_types):
    """Takes an array of IMAGE_TYPE enums and validates them or raises StepFailure."""
    if not set(sign_types).issubset(self._supported_sign_types):
      raise StepFailure('attempting to sign type not in supported sign types')

  @staticmethod
  def massage_channels(channels):
    """Takes an array of common_pb2.Channel & validates & strings them."""
    channels_strs = [Channel.Name(x) for x in channels]
    if 'CHANNEL_UNSPECIFIED' in channels_strs:
      raise StepFailure('invalid channel CHANNEL_UNSPECIFIED')
    return [x.replace('CHANNEL_', '') for x in channels_strs]

  def __init__(self, properties, **kwargs):
    super(CrosReleaseApi, self).__init__(**kwargs)
    self._release_bucket = properties.release_bucket
    self._channels = properties.channels
    self._keyset = properties.keyset
    self._sign_types = properties.sign_types
    self._ensure_no_password = properties.ensure_no_password
    self._firmware_update = properties.firmware_update
    self._dryrun = properties.dryrun
    self._paygen_dryrun = properties.paygen_dryrun

  def schedule_payload_generation(self):
    """Schedule the generation of release payloads using the context of a build.

    This is nonblocking, will launch and return the id for the paygen
    orchestrator. It assumes its being ran after a local build has been made.

    Args:
      build_target_name (str): The builder target name.
      target_chromeos_version (str): The target chromeos version (e.g. '13337.0.1').
      milestone (int): The milestone number.

    Returns:
      The int build id for the launched orchestrator.
    """
    builder = ('staging-paygen-orchestrator'
               if self.m.build_menu.is_staging else 'paygen-orchestrator')
    bucket = 'staging' if self.m.build_menu.is_staging else 'packaging'

    version = self.m.cros_version.read_workspace_version()
    with self.m.step.nest('generate payloads') as presentation:
      paygen_properties = {
          'builder_name': self.m.build_menu.build_target.name,
          'target_chromeos_version': version.platform_version,
          "milestone": int(version.branch),
          'delta_types': [],
          'channels': CrosReleaseApi.massage_channels(self._channels),
          'au_testing_models': [],
          'src_bucket': self._release_bucket,
          'dest_bucket': self._release_bucket,
          'keyset': self._keyset,
          'dryrun': self._paygen_dryrun,
          'delta_payload_test_override': 'RESPECT_CONFIG',
          'full_payload_test_override': 'RESPECT_CONFIG',
      }
      request = self.m.buildbucket.schedule_request(
          builder='paygen-orchestrator', bucket='packaging',
          properties=paygen_properties)
      return self.m.buildbucket.run(
          [request], timeout=self.m.cros_paygen.paygen_orchestrator_timeout_sec,
          step_name='running paygen orchestrator')

  def push_and_sign_images(self):
    """Call the Push Image Build API endpoint for the build.

    This pushes the image files to the appropriate bucket and prepares them
    for signing. The actual execution of these procedures is handled in the
    underlying script, chromite/scripts/push_image.py. Must be used in the
    context of a build.
    """
    version = self.m.cros_version.read_workspace_version().platform_version
    with self.m.step.nest('push images'):
      gs_image_dir = "gs://{bucket}/{target}-release/{version}".format(
          **{
              'bucket': self.m.build_menu.config.artifacts.artifacts_gs_bucket,
              'target': self.m.build_menu.build_target.name,
              'version': version,
          })
      sysroot = Sysroot(build_target=self.m.build_menu.build_target)

      # Validate sign types given.
      self._validate_sign_types(self._sign_types)

      return self.m.cros_artifacts.push_image(
          self.m.build_menu.chroot, gs_image_dir, sysroot,
          sign_types=self._sign_types,
          dest_bucket='gs://' + self._release_bucket)
