# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import base64

from google.protobuf import json_format

from PB.chromiumos.prebuilts_cloud import UpdateSnapshotDataRequest
from PB.recipe_modules.chromeos.binhost_lookup_service import (
    binhost_lookup_service as binhost_lookup_service_pb2)
from recipe_engine import recipe_api


class BinhostLookupServiceApi(recipe_api.RecipeApi):
  """Module for operations related to the binhost lookup service."""

  def __init__(
      self,
      properties: binhost_lookup_service_pb2.BinhostLookupServiceProperties,
      *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._pubsub_project_id = properties.pubsub_project_id
    self._pubsub_topic_id_update_snapshot_data = (
        properties.pubsub_topic_id_update_snapshot_data)

  def _validate(self) -> None:
    """Validate properties for the recipe module."""
    if not self._pubsub_project_id:
      raise recipe_api.InfraFailure('Must set pubsub_project_id')
    if not self._pubsub_topic_id_update_snapshot_data:
      raise recipe_api.InfraFailure(
          'Must set pubsub_topic_id_update_snapshot_data')

  def _publish_event_update_snapshot_data(
      self, snapshot_sha: str, snapshot_num: int, external: bool,
      buildbucket_id: int) -> UpdateSnapshotDataRequest:
    """Publish snapshot metadata to Cloud Pub/Sub.

    Publish a Pub/Sub message to the binhosts lookup service using the
    `cloud_pubsub` recipe module.

    Args:
      snapshot_sha: Unique sha of the snapshot.
      snapshot_num: Snapshot number.
      external: Bool to denote if the snapshot is external.
      buildbucket_id: ID of the annealing builder that created the snapshot.
    """
    self._validate()
    staging_prefix = ('staging-' if self.m.cros_infra_config.is_staging else '')
    snapshots_pubsub_topic_id = (
        f'{staging_prefix}{self._pubsub_topic_id_update_snapshot_data}')

    snapshot_data = UpdateSnapshotDataRequest(snapshot_sha=snapshot_sha,
                                              snapshot_num=snapshot_num,
                                              external=external,
                                              buildbucket_id=buildbucket_id)
    message_serialized = snapshot_data.SerializeToString()
    message_b64 = base64.b64encode(message_serialized).decode()
    self.m.cloud_pubsub.publish_message(self._pubsub_project_id,
                                        snapshots_pubsub_topic_id, message_b64)
    return snapshot_data

  def publish_snapshot_metadata(self, snapshot_sha: str, snapshot_num: int,
                                external: bool, buildbucket_id: int,
                                raise_on_failure: bool = False) -> None:
    """Wrapper function to publish snapshot metadata.

    Provides additional exception handling and sets the step presentation data.

    Args:
      snapshot_sha: Unique sha of the snapshot.
      snapshot_num: Snapshot number.
      external: Bool to denote if the snapshot is external.
      buildbucket_id: ID of the annealing builder that created the snapshot.
      raise_on_failure: Whether to raise an exception on failure.
    """
    internal_or_external = 'external' if external else 'internal'

    with self.m.step.nest(
        f'publish {internal_or_external} snapshot metadata') as presentation:
      try:
        published_snapshot_data = self._publish_event_update_snapshot_data(
            snapshot_sha, snapshot_num, external, buildbucket_id)
        presentation.logs['published event'] = json_format.MessageToJson(
            published_snapshot_data)

      except Exception as e:  # pylint: disable=broad-except
        presentation.logs['caught exception'] = repr(e)
        presentation.step_text = (
            f'Failed to publish {internal_or_external} snapshot '
            'metadata to the binhost lookup service.')
        presentation.status = self.m.step.INFRA_FAILURE

        if raise_on_failure:
          raise e
