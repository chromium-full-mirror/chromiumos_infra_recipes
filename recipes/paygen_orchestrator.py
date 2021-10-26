# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for orchestrating ChromeOS payloads (AU deltas etc)."""

from google.protobuf.json_format import MessageToJson
import itertools
import json
from os import path

from PB.recipes.chromeos.paygen_orchestrator import PaygenOrchestratorProperties
from PB.chromiumos.common import Channel, DeltaType

from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2

from recipe_engine import post_process

DEPS = [
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/step',
    'cros_build_api',
    'cros_paygen',
    'cros_release',
    'cros_source',
    'cros_storage',
    'workspace_util',
]

PROPERTIES = PaygenOrchestratorProperties


def RunSteps(api, properties):
  # Set default values for unspecified properties.
  delta_types = properties.delta_types
  delta_types = delta_types or api.cros_paygen.default_delta_types

  # Get the current paygen configuration.
  with api.step.nest('discovering payload configuration') as pres:
    configured_payloads = []

    # Override RUBIK channel with canary as there are no payload definitions for
    # it. This should be removed once we transition to the main channels.
    # TODO(b:195415535): Remove this.
    override_chan = properties.channels
    if override_chan == [Channel.CHANNEL_RUBIK]:
      override_chan = [Channel.CHANNEL_CANARY]

    for delta_type, channel in itertools.product(delta_types, override_chan):

      delta_t_str, channel_str = (
          DeltaType.Name(delta_type),
          api.cros_release.channel_strip_prefix(channel))

      cfgs = api.cros_paygen.get_builder_configs(properties.builder_name,
                                                 delta_type=delta_t_str,
                                                 channel=channel_str)
      # RUBIK is currently using canary channels payload definitions which will
      # have the channel field set to 'canary'. We need to set the config's
      # channel to 'rubik' in order for the artifact discover logic to match
      # artifacts from the rubik-channel to the config.
      # TODO(b:195415535): Remove this.
      if properties.channels == [Channel.CHANNEL_RUBIK]:
        for cfg in cfgs:
          cfg['channel'] = api.cros_release.channel_strip_prefix(
              Channel.CHANNEL_RUBIK)

      configured_payloads.extend(cfgs)

    pres.logs['%s configured sources' % len(configured_payloads)] = (
        json.dumps(configured_payloads, indent=2))

    # If no payloads are configured return (that was easy!).
    if not configured_payloads:
      pres.step_text = 'no configurations matched in payload.json'
      return

  # Get all the artifacts in the source(s) and target locations.
  target_artifacts, source_artifacts = [], []
  for channel in properties.channels:

    # e.g. beta-channel, beta
    long_chan_name, short_chan_name = (
        api.cros_release.channel_dash_suffix(channel),
        api.cros_release.channel_strip_prefix(channel))

    with api.step.nest('examining %s' % long_chan_name):

      # Iterate the configured payloads and find artifacts at each source.
      with api.step.nest('source artifacts'):
        # Create Source Image definitions based upon the configuration alone.
        for payload_cfg in configured_payloads:
          if payload_cfg['channel'] == short_chan_name:
            found_arts = api.cros_storage.discover_gs_artifacts(
                path.join('gs://' + properties.src_bucket, long_chan_name,
                          payload_cfg['builder_name'],
                          payload_cfg['chrome_os_version']),
                parse_types=api.cros_storage.image_types)
            source_artifacts.extend([x.to_proto() for x in found_arts])

      # Discover the target images for this channel.
      with api.step.nest('target artifacts'):
        found_arts = api.cros_storage.discover_gs_artifacts(
            path.join('gs://' + properties.src_bucket, long_chan_name,
                      properties.builder_name,
                      properties.target_chromeos_version),
            parse_types=api.cros_storage.image_types)
        target_artifacts.extend([x.to_proto() for x in found_arts])

  # Match configuration with discovered artifacts.
  with api.step.nest('discovered artifacts') as pres:
    pres.logs['target_artifacts'] = [MessageToJson(x) for x in target_artifacts]
    pres.logs['source_artifacts'] = [MessageToJson(x) for x in source_artifacts]

  # Aka: "Child Build Requests".
  cbr = []

  # Find the src and tgt artifacts applicable for each configured payload
  # and construct the child requests. Report missing artifacts.
  # TODO(crbug.com/1122854): Missing artifacts are silently ignored.
  with api.step.nest('pairing artifacts') as pres:

    # Do N2N testing payloads.
    cbr.extend(
        api.cros_paygen.get_n2n_requests(target_artifacts,
                                         properties.dest_bucket, True,
                                         properties.dryrun))

    # Do configured delta payloads.
    for payload_cfg in configured_payloads:
      reqs = api.cros_paygen.get_delta_requests(payload_cfg, source_artifacts,
                                                target_artifacts,
                                                properties.dest_bucket, True,
                                                properties.keyset,
                                                properties.dryrun)
      cbr.extend(reqs)
    pres.logs['%s deltas' % len(cbr)] = [MessageToJson(x) for x in cbr]

    # Do full payloads.
    reqs = api.cros_paygen.get_full_requests(target_artifacts,
                                             properties.dest_bucket, True,
                                             properties.keyset,
                                             properties.dryrun)
    pres.logs['%s full' % len(reqs)] = [MessageToJson(x) for x in reqs]
    cbr.extend(reqs)

    if not cbr:
      pres.step_text = 'No payload pairs (src->tgt) found.'
      return
    else:
      pres.step_text = '%s payloads found.' % len(cbr)

  # Schedule child builders.
  res = api.cros_paygen.run_paygen_builders(
      cbr, configured_payloads, properties.delta_payload_test_override,
      properties.full_payload_test_override)

  with api.step.nest('results') as pres:
    suc = [x for x in res if x.status == common_pb2.SUCCESS]
    fail = [x for x in res if x.status != common_pb2.SUCCESS]
    pres.step_text = '%s of %s passed' % (len(suc), (len(suc) + len(fail)))

  # Launch AU tests if configured, don't wait for them.


def GenTests(api):

  def get_props(delta_types=None, builder_name='coral',
                target_chromeos_version='13505.15.0', channels=None):
    delta_types = delta_types or ['OMAHA']
    channels = channels or ['CHANNEL_DEV', 'CHANNEL_BETA']
    props = api.properties(delta_types=delta_types, builder_name=builder_name,
                           target_chromeos_version=target_chromeos_version,
                           channels=channels)
    return props

  good_paygen_cfg = api.cros_paygen.test_paygen(
      'discovering payload configuration.get paygen json.gsutil cat',
      api.cros_paygen.EXAMPLE_PAYGEN_JSON)

  yield api.test(
      'basic', get_props(), good_paygen_cfg,
      api.cros_storage.test_listing('examining beta-channel.source artifacts.'
                                    'discover gs artifacts.gsutil list'),
      api.cros_storage.test_listing('examining beta-channel.source artifacts.'
                                    'discover gs artifacts (2).gsutil list'),
      api.cros_storage.test_listing(
          'examining beta-channel.target artifacts.'
          'discover gs artifacts.gsutil list',
          test_data=api.cros_storage.TEST_TGT_LS_OUTPUT_TEXT),
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.MustRun, 'pairing artifacts'),
      api.post_check(post_process.MustRun, 'results'))

  yield api.test('no-payloads', get_props(builder_name='goobolywhobbly'),
                 good_paygen_cfg, api.post_check(post_process.StatusSuccess))

  # Successful lists but don't find a suitable pair in get_requests().
  yield api.test(
      'no-pairs', get_props(), good_paygen_cfg,
      api.cros_storage.test_listing('examining beta-channel.source artifacts.'
                                    'discover gs artifacts.gsutil list'),
      api.cros_storage.test_listing('examining beta-channel.source artifacts.'
                                    'discover gs artifacts (2).gsutil list'),
      api.cros_storage.test_listing(
          'examining beta-channel.target artifacts.'
          'discover gs artifacts.gsutil list',
          test_data='gs://chromeos-releases/beta-channel/coral/13505.15.0/'
          'ChromeOS-factory-R87-13505.15.0-coral.tar.xz'),
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.DoesNotRun, 'running children'))

  # TODO(b:195415535): Remove this with channel RUBIK.
  rubik_override_paygen_cfg = api.cros_paygen.test_paygen(
      'discovering payload configuration.get paygen json.gsutil cat',
      api.cros_paygen.RUBIK_OVERRIDE_PAYGEN_JSON)

  yield api.test('rubik-override', get_props(channels=['CHANNEL_RUBIK']),
                 rubik_override_paygen_cfg)
