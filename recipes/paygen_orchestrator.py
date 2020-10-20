# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for orchestrating ChromeOS payloads (AU deltas etc)."""

from google.protobuf import json_format
import itertools
import json
from os import path
import string

from PB.recipes.chromeos.paygen_orchestrator import PaygenOrchestratorProperties
from PB.chromite.api.payload import Build, SignedImage, UnsignedImage

from google.protobuf.json_format import MessageToJson
from recipe_engine import post_process

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_build_api',
    'cros_paygen',
    'cros_sdk',
    'cros_source',
    'cros_storage',
    'workspace_util',
]

PROPERTIES = PaygenOrchestratorProperties

PAYGEN_CHILDREN_TIMEOUT_SEC = 60 * 60 * 6


# TODO(engeg@): These are ugly, we should write a cros_channel module to handle.
def LongChannelName(channel_enum_val):
  """Takes the integer enum value and outputs suffix'd string form."""
  return (PaygenOrchestratorProperties.Channel.Name(channel_enum_val).lower() +
          '-channel')


def ShortChannelName(channel_enum_val):
  """Takes the integer enum value and outputs non-suffix'd string form."""
  return PaygenOrchestratorProperties.Channel.Name(channel_enum_val).lower()


def RunSteps(api, properties):
  # Massage properties w.r.t. empty defaults
  delta_types = properties.delta_types
  delta_types = delta_types or api.cros_paygen.default_delta_types

  # Get the current paygen configuration.
  with api.step.nest('discovering payload configuration') as pres:
    configured_payloads = []
    for delta_type, channel in itertools.product(delta_types,
                                                 properties.channels):
      delta_t_str, channel_str = (
          PaygenOrchestratorProperties.DeltaType.Name(delta_type),
          PaygenOrchestratorProperties.Channel.Name(channel))

      cfg = api.cros_paygen.get_builder_config(properties.builder_name,
                                               delta_type=delta_t_str,
                                               channel=channel_str)
      configured_payloads.extend(cfg)

    pres.logs['%s configured sources' % len(configured_payloads)] = (
        json.dumps(configured_payloads, indent=2))

  # If no payloads are configured return (that was easy!).
  if not configured_payloads:
    with api.step.nest('no configurations matched in payload.json!'):
      return

  target_artifacts, source_artifacts = [], []
  for channel in properties.channels:
    long_chan_name = LongChannelName(channel)
    with api.step.nest('examining %s' % long_chan_name) as pres:

      # Create Source Image definitions based upon the configuration alone.
      for payload_def in configured_payloads:
        if payload_def['channel'] == ShortChannelName(channel):
          src_artifacts = api.cros_storage.DiscoverGSArtifacts(
              path.join('gs://' + properties.bucket, long_chan_name,
                        payload_def['builder_name'],
                        payload_def['chrome_os_version']))
          for art in src_artifacts:
            source_artifacts.append(art.to_proto())

      # Discover the Images that exist at the remote path.
      tgt_artifacts = api.cros_storage.DiscoverGSArtifacts(
          path.join('gs://' + properties.bucket, long_chan_name,
                    properties.builder_name,
                    properties.target_chrome_os_version))

      for art in tgt_artifacts:
        target_artifacts.append(art.to_proto())

  # Match configuration with discovered artifacts.
  with api.step.nest('discovered artifacts') as pres:
    pres.logs['target_artifacts'] = [
        json_format.MessageToJson(x) for x in target_artifacts
    ]
    pres.logs['source_artifacts'] = [
        json_format.MessageToJson(x) for x in source_artifacts
    ]

  # Find the src and tgt artifacts applicable for each configured payload
  # and construct the child request. Report missing artifacts.
  child_build_requests = []
  with api.step.nest('pairing artifacts') as pres:
    for cfg in configured_payloads:
      pass

  # Schedule child builders.

  # Collect and handle failures.

  # Schedule AU tests if configured, don't wait for them.


def GenTests(api):

  def get_props(delta_types=['OMAHA'], builder_name='octopus',
                target_chrome_os_version='12345.0.0', channels=['DEV', 'BETA']):
    props = api.properties(delta_types=delta_types, builder_name=builder_name,
                           target_chrome_os_version=target_chrome_os_version,
                           channels=channels)
    return props

  good_paygen = api.cros_paygen.mock_paygen(
      'discovering payload configuration.get paygen json.gsutil cat',
      api.cros_paygen.EXAMPLE_PAYGEN_JSON)

  yield api.test(
      'basic', get_props(), good_paygen,
      api.cros_storage.normal_test_data(
          'examining beta-channel.discover gs artifacts.gsutil list'),
      api.cros_storage.normal_test_data(
          'examining dev-channel.discover gs artifacts.gsutil list'),
      api.post_check(post_process.StatusSuccess))

  yield api.test('no-payloads', get_props(builder_name='goobolywhobbly'),
                 good_paygen, api.post_check(post_process.StatusSuccess))
