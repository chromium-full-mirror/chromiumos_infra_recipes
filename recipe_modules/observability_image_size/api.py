# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import base64
from typing import Iterable

from google.protobuf.json_format import MessageToJson

from PB.chromite.api.observability import GetImageSizeDataRequest
from PB.chromite.observability.sizes import ImageSizeObservabilityData
from recipe_engine import recipe_api


class ObservabilityImageSizeApi(recipe_api.RecipeApi):
  """Collect image size data."""

  def __init__(self, properties, *args, **kwargs):
    super().__init__(*args, **kwargs)
    # TODO(b/224589938): Determine what these IDs should be
    self._pubsub_project_id = properties.pubsub_project_id or "cros-build-telemetry"
    self._pubsub_topic_id = properties.pubsub_topic_id or "image-size-events"
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
      chroot: ' PB.chromiumos.common.Chroot' = None) -> bool:
    """Get image/partition/package size data.

    Args:
      image_data: The images that were built.

    Returns:
      bool: False when the endpoint could not be called, True otherwise.
    """
    if not self.m.cros_build_api.has_endpoint(
        self.m.cros_build_api.ObservabilityService, 'GetImageSizeData'):
      # Branch doesn't have the endpoint.
      return False

    with self.m.step.nest('add data from images'):
      request = GetImageSizeDataRequest(built_images=image_data, chroot=chroot)
      response = self.m.cros_build_api.ObservabilityService.GetImageSizeData(
          request)
      for img_data in response.image_data:
        self._data_proto.image_data.add().CopyFrom(img_data)

      return True

  def publish(self, config, build_target, target_versions, built_images,
              chroot):
    """Collect and publish the image size data."""
    with self.m.step.nest('collect image size data') as pres:
      if not config.general.publish_image_sizes:
        pres.step_text = 'Skipped: Image size publishing disabled.'
        return

      if not built_images:
        raise recipe_api.StepFailure('No images provided.')

      if not self._get_image_size_data(built_images, chroot):
        pres.step_text = 'Skipped: Image size data could not be collected.'
        return

      self._add_target_versions(target_versions)
      self._add_builder_metadata(config, build_target)

      pres.logs['image_data.json'] = MessageToJson(self._data_proto)
      with self.m.step.nest('publish image size data'):
        # Data is passed to the publish-message support binary via JSON. The
        # serialized proto must be base64 encoded to prevent UnicodeDecodeErrors.
        # It will be unencoded by the publish-message support binary before it
        # is published.
        data_serialized = self._data_proto.SerializeToString(deterministic=True)
        data_b64 = base64.b64encode(data_serialized).decode()
        self.m.cloud_pubsub.publish_message(self._pubsub_project_id,
                                            self._pubsub_topic_id, data_b64)
