# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=protected-access

"""API for working with Paygen. Used by paygen.py."""
# TODO(b/316602091): Rename this module to `paygen_util` or something else
# unrelated to testing.

import json
from typing import Optional

from PB.chromiumos import common as common_pb2  # pylint: disable=unused-import
from PB.chromite.api.payload import GenerationRequest
from PB.chromiumos.build_report import BuildReport
from PB.chromiumos.build_report import URI
from PB.recipes.chromeos.paygen import PaygenProperties
from recipe_engine import recipe_api


class PaygenTestingApi(recipe_api.RecipeApi):
  """A module for CrOS-specific paygen testing steps."""

  def _get_channel_from_paygen_request(
      self, gen_req: GenerationRequest) -> Optional['common_pb2.Channel']:
    """Get the target channel from a paygen request input properties.

    When creating a build report we look at the input arguments of the finished
    paygen builders. In the generation_request we pull the target channel and
    return this for reporting. Deals with the one_of by returning the first
    found.

    Args:
      gen_req: A GenerationRequest struct, as extracted from a broader build_pb2.Build request.
    Returns:
      A chromiumos.Channel.
    """
    if gen_req.HasField('tgt_signed_image'):
      return self.m.cros_release_util.channel_long_string_to_enum(
          gen_req.tgt_signed_image.build.channel)
    if gen_req.HasField('tgt_unsigned_image'):
      return self.m.cros_release_util.channel_long_string_to_enum(
          gen_req.tgt_unsigned_image.build.channel)
    if gen_req.HasField('tgt_dlc_image'):
      return self.m.cros_release_util.channel_long_string_to_enum(
          gen_req.tgt_dlc_image.build.channel)
    return None  #pragma: nocover

  def create_paygen_build_report_payload(
      self, req: PaygenProperties.PaygenRequest, payload_uri: str,
      recovery_key_version: Optional[int] = None) -> BuildReport.Payload:
    """Prepare payload information for the release pubsub.

    Args:
      req: The paygen request that was used.
      payload_uri: The uri of the generated payload.
      recovery_key_version: version of the recovery key if provided. Default
        None.

    Returns:
      A Payload containing payload information for the pubsub.
    """

    # If paygen was skipped (minios) this will be empty, so skip it.
    if not payload_uri:
      return None

    # Assign generation request for shorthand access.
    gen_req = req.generation_request

    # Determine payload type from the paygen request.
    payload_type = BuildReport.Payload.PayloadType.PAYLOAD_TYPE_STANDARD
    if gen_req and gen_req.minios:
      payload_type = BuildReport.Payload.PayloadType.PAYLOAD_TYPE_MINIOS
    elif gen_req.HasField('tgt_dlc_image'):
      payload_type = BuildReport.Payload.PayloadType.PAYLOAD_TYPE_DLC

    payload_json_path = '{}.json'.format(payload_uri)
    payload_info = self.m.gsutil.cat(
        payload_json_path, name='cat {}'.format(payload_json_path),
        stdout=self.m.raw_io.output(add_output_log=True)).stdout
    payload_info = json.loads(payload_info)

    is_delta = BuildReport.BuildArtifact.Type.PAYLOAD_FULL
    if payload_info.get('is_delta', False):
      is_delta = BuildReport.BuildArtifact.Type.PAYLOAD_DELTA

    return BuildReport.Payload(
        payload=BuildReport.BuildArtifact(
            type=is_delta,
            uri=URI(gcs=payload_uri),
            sha256=payload_info['sha256_hex'],
        ), payload_type=payload_type, appid=payload_info['appid'],
        channel=self._get_channel_from_paygen_request(gen_req),
        metadata_signature=payload_info['metadata_signature'],
        metadata_size=int(payload_info['metadata_size']),
        source_version=payload_info.get('source_version', None),
        target_version=payload_info['target_version'], size=int(
            payload_info['size']), recovery_key_version=recovery_key_version)
