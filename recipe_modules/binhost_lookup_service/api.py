# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""APIs to interact with the binhost lookup service."""

import base64

from google.protobuf import json_format
from google.protobuf import message

from PB.chromiumos import common as common_pb2
from PB.chromiumos import prebuilts_cloud as prebuilts_cloud_pb2
from PB.recipe_modules.chromeos.binhost_lookup_service import (
    binhost_lookup_service as binhost_lookup_service_pb2)
from recipe_engine import engine_types
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
    self._pubsub_topic_id_update_binhost_data = (
        properties.pubsub_topic_id_update_binhost_data)

  def _validate(self) -> None:
    """Validate properties for the recipe module."""
    if not self._pubsub_project_id:
      raise recipe_api.InfraFailure('Must set pubsub_project_id')
    if not self._pubsub_topic_id_update_snapshot_data:
      raise recipe_api.InfraFailure(
          'Must set pubsub_topic_id_update_snapshot_data')
    if not self._pubsub_topic_id_update_binhost_data:
      raise recipe_api.InfraFailure(
          'Must set pubsub_topic_id_update_binhost_data')

  def _publish_msg_to_pubsub(self, msg: message.Message, topic: str) -> None:
    """Publish a message to the given Pub/Sub topic.

    Args:
      msg: A populated proto message to send to the Pub/Sub topic.
      topic: The topic to publish to. If this is a staging builder, then this
        method will automatically prepend "staging-" to the topic.
    """
    self._validate()
    if self.m.cros_infra_config.is_staging:  # Prefix PubSub topic name based on the env.
      topic = f'staging-{topic}'
    else:
      topic = f'prod-{topic}'
    msg_serialized = msg.SerializeToString()
    msg_b64 = base64.b64encode(msg_serialized).decode()
    self.m.cloud_pubsub.publish_message(self._pubsub_project_id, topic, msg_b64)

  def _handle_publish_exception(
      self, exception: Exception, msg_type: str, raise_on_failure: bool,
      step_presentation: engine_types.StepPresentation) -> None:
    """Helper function to handle exceptions while publishing to Pub/Sub.

    Args:
      exception: The exception object to handle.
      msg_type: Type of message being published to Pub/Sub. This is used here
        for logging purposes.
      raise_on_failure: Whether to raise an exception on failure. This should be
        passed from the calling function.
      step_presentation: Step presentation object to add the logs to.
    """
    step_presentation.logs['caught exception'] = repr(exception)
    step_presentation.step_text = (
        f'Failed to publish {msg_type} to the binhost lookup service.')
    step_presentation.status = self.m.step.INFRA_FAILURE
    if raise_on_failure:
      raise exception

  def publish_snapshot_metadata(self, snapshot_sha: str, snapshot_num: int,
                                external: bool, buildbucket_id: int,
                                raise_on_failure: bool = False) -> None:
    """Publish snapshot metadata to Cloud Pub/Sub.

    Publish a Pub/Sub message to the binhost lookup service using the
    `cloud_pubsub` recipe module.

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
        snapshot_data = prebuilts_cloud_pb2.UpdateSnapshotDataRequest(
            snapshot_sha=snapshot_sha, snapshot_num=snapshot_num,
            external=external, buildbucket_id=buildbucket_id)
        self._publish_msg_to_pubsub(snapshot_data,
                                    self._pubsub_topic_id_update_snapshot_data)
        presentation.logs['published event'] = json_format.MessageToJson(
            snapshot_data)
      except Exception as e:  # pylint: disable=broad-except
        self._handle_publish_exception(
            e, f'{internal_or_external} snapshot metadata', raise_on_failure,
            presentation)

  def publish_binhost_metadata(self, build_target: common_pb2.BuildTarget,
                               profile: common_pb2.Profile, snapshot_sha: str,
                               gs_uri: str, gs_bucket_name: str,
                               buildbucket_id: int, complete: bool,
                               private: bool,
                               raise_on_failure: bool = False) -> None:
    """Publish binhost metadata to Cloud Pub/Sub.

    Publish a Pub/Sub message to the binhost lookup service using the
    `cloud_pubsub` recipe module.

    Args:
      build_target: The system CrOS is being built for, also known as board.
      profile: Name of the profile to use with the build_target.
      snapshot_sha: Unique sha of the snapshot.
      gs_uri: Location of the binhost object in google storage.
      gs_bucket_name: Name of the google storage bucket which contains the
          binhost.
      buildbucket_id: Id of the postsubmit builder that created and
          uploaded the binhost.
      complete: Bool to indicate if this binhost contains all the binpkgs
          specified in the packages metadata file.
      private: Bool to indicate if the binhost is private.
      raise_on_failure: Whether to raise an exception on failure.
    """
    with self.m.step.nest('publish binhost metadata') as presentation:
      try:
        binhost_data = prebuilts_cloud_pb2.UpdateBinhostDataRequest(
            build_target=build_target.name, profile=profile.name,
            snapshot_sha=snapshot_sha, gs_uri=gs_uri,
            gs_bucket_name=gs_bucket_name, buildbucket_id=buildbucket_id,
            complete=complete, private=private)
        self._publish_msg_to_pubsub(binhost_data,
                                    self._pubsub_topic_id_update_binhost_data)
        presentation.logs['published event'] = json_format.MessageToJson(
            binhost_data)
      except Exception as e:  # pylint: disable=broad-except
        self._handle_publish_exception(e, 'binhost metadata', raise_on_failure,
                                       presentation)
