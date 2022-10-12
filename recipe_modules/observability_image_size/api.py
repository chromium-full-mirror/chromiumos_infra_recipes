# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json

from google.protobuf import json_format

from PB.chromite.api.observability import GetImageSizeDataRequest
from PB.chromite.observability.sizes import ImageSizeObservabilityData

from recipe_engine import recipe_api


def py2_MessageToJson(obj):
  # TODO(b/217973414): Delete once we don't need to fix the separator spacing
  # between py2 and py3 MessageToJson and replace usages with MessageToJson.
  return json.dumps(
      json_format.MessageToDict(obj), separators=(',', ': '), indent=2,
      sort_keys=True)


class ObservabilityImageSizeApi(recipe_api.RecipeApi):
  """Collect image size data."""

  def __init__(self, properties, *args, **kwargs):
    super(ObservabilityImageSizeApi, self).__init__(*args, **kwargs)
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
      self._data_proto.builder_metadata.annealing_commit_id = self.m.cros_version.version.snapshot
      # TODO: get manifest_commit

  def _get_image_size_data(self, image_data):
    """Get image/partition/package size data."""
    with self.m.step.nest('add data from images'):
      request = GetImageSizeDataRequest(built_images=image_data)
      response = self.m.cros_build_api.ObservabilityService.GetImageSizeData(
          request)
      for img_data in response.image_data:
        self._data_proto.image_data.add().CopyFrom(img_data)

  def publish(self, config, build_target, target_versions, built_images):
    """Collect and publish the image size data."""
    with self.m.step.nest('collect image size data') as pres:
      if not config.general.publish_image_sizes:
        pres.step_text = 'Skipped: Image size publishing disabled.'
        return

      if not built_images:
        raise recipe_api.StepFailure('No images provided.')

      self._add_target_versions(target_versions)
      self._add_builder_metadata(config, build_target)
      self._get_image_size_data(built_images)
      pres.logs['image_data.json'] = py2_MessageToJson(self._data_proto)
      with self.m.step.nest('publish image size data'):
        # TODO(build): implement publication of image size proto
        pass
