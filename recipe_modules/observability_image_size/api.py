# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for retrieving image and package size data."""

import base64
from typing import Iterable, Optional, Dict

from google.protobuf.json_format import MessageToJson

from PB.chromite.api.observability import GetImageSizeDataRequest
from PB.chromite.observability.sizes import ImageSizeObservabilityData
from recipe_engine import recipe_api


class ObservabilityImageSizeApi(recipe_api.RecipeApi):
  """Collect image size data."""

  def __init__(self, properties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    # TODO(b/224589938): Determine what these IDs should be
    self._pubsub_project_id = properties.pubsub_project_id or 'cros-build-telemetry'
    self._pubsub_topic_id = properties.pubsub_topic_id or 'image-size-events'
    self._data_proto = ImageSizeObservabilityData()

  def _add_target_versions(self, version_data_response):
    """Add data from GetTargetVersions to the image size data.

    Args:
      version_data_response (GetTargetVersionsResponse): The response from
        PackageService/GetTargetVersions.
    """
    with self.m.step.nest('add version data'):
      self._data_proto.build_version_data.milestone = int(
          version_data_response.milestone_version)
      pv = [int(x) for x in version_data_response.platform_version.split('.')]
      if len(pv) != 3:
        raise recipe_api.StepFailure('Invalid platform version {}'.format(
            version_data_response.platform_version))
      build, branch, patch = pv
      self._data_proto.build_version_data.platform_version.platform_build = build
      self._data_proto.build_version_data.platform_version.platform_branch = branch
      self._data_proto.build_version_data.platform_version.platform_patch = patch

  def _add_builder_metadata(self, config, build_target):
    """Add the required builder metadata to the image size data.

    Args:
      config (BuilderConfig): The builder config.
      build_target (BuildTarget): The build target.
    """
    with self.m.step.nest('add metadata from builder'):
      self._data_proto.builder_metadata.build_target.name = build_target.name
      self._data_proto.builder_metadata.buildbucket_id = self.m.buildbucket.build.id
      self._data_proto.builder_metadata.start_timestamp.CopyFrom(
          self.m.buildbucket.build.start_time)
      self._data_proto.builder_metadata.build_type = config.id.type
      self._data_proto.builder_metadata.build_config_name = config.id.name
      self._data_proto.builder_metadata.annealing_commit_id = (
          self.m.cros_version.version.snapshot or 0)
      self._data_proto.builder_metadata.manifest_commit = self.m.src_state.gitiles_commit.id

  def _get_image_size_data(
      self, image_data: Iterable['PB.chromite.api.image.Image'],
      chroot: ' PB.chromiumos.common.Chroot' = None
  ) -> Optional[
      'PB.chromite.api.observability.ObservabilityService.GetImageSizeDataResponse']:
    """Get image/partition/package size data.

    Args:
      image_data: The images that were built.

    Returns:
      bool: False when the endpoint could not be called, True otherwise.
    """
    if not self.m.cros_build_api.has_endpoint(
        self.m.cros_build_api.ObservabilityService, 'GetImageSizeData'):
      # Branch doesn't have the endpoint.
      return None

    with self.m.step.nest('add data from images'):
      request = GetImageSizeDataRequest(built_images=image_data, chroot=chroot)
      response = self.m.cros_build_api.ObservabilityService.GetImageSizeData(
          request)
      for img_data in response.image_data:
        self._data_proto.image_data.add().CopyFrom(img_data)

      return response

  def _extract_gerrit_binary_sizes(
      self, get_image_size_data_response_proto) -> Dict[str, int]:
    """Gets select subset of image sizes.

    As written, this will only get the total size of each partition for each
    image built. Packages may be added at a later date.

    The dictionary generated here uses the specification from the plugin's
    README: https://chromium.googlesource.com/infra/gerrit-plugins/binary-size/+/refs/heads/main#how-it-works.

    Args:
      image_data_proto: The image + package size proto.

    Returns:
      A dictionary containing the size information used in Gerrit's plugin.
    """
    result = {}
    for img_data in get_image_size_data_response_proto.image_data:
      for partition in img_data.image_partition_data:
        result |= {
            f'{img_data.image_type}.{partition.partition_name}':
                partition.partition_disk_utilization_size
        }
        # Note that a budget and owner field are excluded for now. These can
        # be added at a later date per the plugin's specification.
    return result


  def publish(self, config, build_target, target_versions, built_images,
              chroot):
    """Collect and publish the image size data."""
    with self.m.step.nest('collect image size data') as pres:
      if not built_images:
        raise recipe_api.StepFailure('No images provided.')

      image_size_data = self._get_image_size_data(built_images, chroot)
      if not image_size_data:
        pres.step_text = 'Skipped: Image size data could not be collected.'
        return

      # Add a hyper-selective subset of proto data to output properties to
      # support Gerrit's binary-size plugin.
      with self.m.step.nest('add image size data to output properties'):
        gerrit_bin_data_json = self._extract_gerrit_binary_sizes(
            image_size_data)
        self.m.easy.set_properties_step(binary_sizes=gerrit_bin_data_json)

      self._add_target_versions(target_versions)
      self._add_builder_metadata(config, build_target)

      pres.logs['image_data.json'] = MessageToJson(self._data_proto)

      # With Gerrit binary-size plugin usage, we have reason to always collect
      # data, but not necessarily to publish sizes for all builder variants.
      # This is expected to add ~45 seconds of overhead to builders that don't
      # have publishing enabled, since the BAPI call to walk the tree and
      # collect this data is the expensive part of the operation.
      if not config.general.publish_image_sizes:
        pres.step_text = 'Skipped: Image size publishing disabled.'
        return

      with self.m.step.nest('publish image size data'):
        # Data is passed to the publish-message support binary via JSON. The
        # serialized proto must be base64 encoded to prevent UnicodeDecodeErrors.
        # It will be unencoded by the publish-message support binary before it
        # is published.
        data_serialized = self._data_proto.SerializeToString(deterministic=True)
        data_b64 = base64.b64encode(data_serialized).decode()
        self.m.cloud_pubsub.publish_message(self._pubsub_project_id,
                                            self._pubsub_topic_id, data_b64)
