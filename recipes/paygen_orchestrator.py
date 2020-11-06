# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for orchestrating ChromeOS payloads (AU deltas etc)."""

from google.protobuf.json_format import MessageToDict
from google.protobuf.json_format import MessageToJson
import itertools
import json
from os import path
import string

from PB.recipes.chromeos.paygen import PaygenProperties
from PB.recipes.chromeos.paygen_orchestrator import PaygenOrchestratorProperties
from PB.chromite.api.payload import Build
from PB.chromite.api.payload import GenerationRequest
from PB.chromite.api.payload import SignedImage
from PB.chromite.api.payload import UnsignedImage

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from recipe_engine import post_process

DEPS = [
    'recipe_engine/buildbucket',
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


# TODO(crbug.com/1122854): These are ugly, we should write a cros_channel module to handle.
def _long_channel_name(channel_enum_val):
  """Takes the integer enum value and outputs suffix'd string form."""
  return (PaygenOrchestratorProperties.Channel.Name(channel_enum_val).lower() +
          '-channel')


def _short_channel_name(channel_enum_val):
  """Takes the integer enum value and outputs non-suffix'd string form."""
  return PaygenOrchestratorProperties.Channel.Name(channel_enum_val).lower()


def RunSteps(api, properties):
  # Set default values for unspecified properties.
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
      pres.step_text = 'no configurations matched in payload.json'
      return

  # Get all the artifacts in the source(s) and target locations.
  target_artifacts, source_artifacts = [], []
  for channel in properties.channels:
    long_chan_name = _long_channel_name(channel)
    with api.step.nest('examining %s' % long_chan_name):

      # Create Source Image definitions based upon the configuration alone.
      for payload_cfg in configured_payloads:
        if payload_cfg['channel'] == _short_channel_name(channel):
          found_arts = api.cros_storage.discover_gs_artifacts(
              path.join('gs://' + properties.bucket, long_chan_name,
                        payload_cfg['builder_name'],
                        payload_cfg['chrome_os_version']))
          for art in found_arts:
            source_artifacts.append(art.to_proto())

      # Discover the Images that exist at the remote path.
      found_arts = api.cros_storage.discover_gs_artifacts(
          path.join('gs://' + properties.bucket, long_chan_name,
                    properties.builder_name,
                    properties.target_chrome_os_version))

      for art in found_arts:
        target_artifacts.append(art.to_proto())

  # Match configuration with discovered artifacts.
  with api.step.nest('discovered artifacts') as pres:
    pres.logs['target_artifacts'] = [MessageToJson(x) for x in target_artifacts]
    pres.logs['source_artifacts'] = [MessageToJson(x) for x in source_artifacts]

  # Aka: "Child Build Requests".
  cbr = []

  # Find the src and tgt artifacts applicable for each configured payload
  # and construct the child requests. Report missing artifacts.
  # TODO(crbug.com/1122854): Missing but expected artifacts are silently ignored.
  with api.step.nest('pairing artifacts') as pres:

    # Do configured delta payloads.
    for payload_cfg in configured_payloads:
      reqs = api.cros_paygen.get_delta_requests(payload_cfg, source_artifacts,
                                                target_artifacts,
                                                properties.bucket, True,
                                                properties.keyset,
                                                properties.dryrun)
      cbr.extend(reqs)
    pres.logs['delta'] = [MessageToJson(x) for x in cbr]

    # Do full payloads.
    reqs = api.cros_paygen.get_full_requests(target_artifacts,
                                             properties.bucket, True,
                                             properties.keyset,
                                             properties.dryrun)
    pres.logs['full'] = [MessageToJson(x) for x in reqs]
    cbr.extend(reqs)

    # Do dlc payloads.
    # TODO(crbug.com/1122854): Impl.

    if not cbr:
      pres.step_text = 'No payload pairs (src->tgt) found.'
      return

  # Schedule child builders.
  br = [
      api.buildbucket.schedule_request(bucket='packaging', builder='paygen',
                                       properties={'request': MessageToDict(x)})
      for x in cbr
  ]

  # TODO(engeg@): Only schedule one, as we're testing and bot cap is low.
  res = api.buildbucket.run(br[0:1], timeout=PAYGEN_CHILDREN_TIMEOUT_SEC,
                            step_name='running children')

  with api.step.nest('results') as pres:
    suc = [x for x in res if x.status == common_pb2.SUCCESS]
    fail = [x for x in res if x.status != common_pb2.SUCCESS]
    pres.step_text = '%s of %s passed' % (len(suc), len(br))

  # Launch AU tests if configured, don't wait for them.


def GenTests(api):

  def get_props(delta_types=None, builder_name='coral',
                target_chrome_os_version='13505.15.0', channels=None):
    delta_types = delta_types or ['OMAHA']
    channels = channels or ['DEV', 'BETA']
    props = api.properties(delta_types=delta_types, builder_name=builder_name,
                           target_chrome_os_version=target_chrome_os_version,
                           channels=channels)
    return props

  good_paygen_cfg = api.cros_paygen.test_paygen(
      'discovering payload configuration.get paygen json.gsutil cat',
      api.cros_paygen.EXAMPLE_PAYGEN_JSON)

  yield api.test(
      'basic', get_props(), good_paygen_cfg,
      api.cros_storage.test_listing(
          'examining beta-channel.discover gs artifacts.gsutil list'),
      api.cros_storage.test_listing(
          'examining beta-channel.discover gs artifacts (2).gsutil list'),
      api.cros_storage.test_listing(
          'examining beta-channel.discover gs artifacts (3).gsutil list',
          test_data=api.cros_storage.TEST_TGT_LS_OUTPUT_TEXT),
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.MustRun, 'pairing artifacts'),
      api.post_check(post_process.MustRun, 'results'))

  yield api.test('no-payloads', get_props(builder_name='goobolywhobbly'),
                 good_paygen_cfg, api.post_check(post_process.StatusSuccess))

  # Successful lists but don't find a suitable pair in get_requests().
  yield api.test(
      'no-pairs', get_props(), good_paygen_cfg,
      api.cros_storage.test_listing(
          'examining beta-channel.discover gs artifacts.gsutil list'),
      api.cros_storage.test_listing(
          'examining beta-channel.discover gs artifacts (2).gsutil list'),
      api.cros_storage.test_listing(
          'examining beta-channel.discover gs artifacts (3).gsutil list',
          test_data='gs://chromeos-releases/beta-channel/coral/13505.15.0/ChromeOS-factory-R87-13505.15.0-coral.tar.xz'
      ), api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.DoesNotRun, 'running children'))
