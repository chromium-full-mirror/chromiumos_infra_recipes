# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for orchestrating ChromeOS payloads (AU deltas etc)."""

import itertools
import json
import string

from PB.recipes.chromeos.paygen_orchestrator import PaygenOrchestratorProperties

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
    'workspace_util',
]

PROPERTIES = PaygenOrchestratorProperties


def RunSteps(api, properties):
  # Massage properties w.r.t. empty defaults
  delta_types = properties.delta_types
  delta_types = delta_types or api.cros_paygen.default_delta_types

  # Get the current paygen configuration.
  with api.step.nest('discovering configuration') as pres:
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

    pres.logs['%s payloads' % len(configured_payloads)] = (
        json.dumps(configured_payloads, indent=2))

  # If no payloads are configured return (that was easy!).
  if not configured_payloads:
    with api.step.nest('no payloads matched in payload.json!'):
      return

  # Generate sub requests.
  with api.workspace_util.setup_workspace(), \
                  api.cros_sdk.cleanup_context():
    # Sync chromite only.
    api.cros_source.ensure_synced_cache(projects=['chromiumos/chromite'])

    # Call build api to discover build images.

    # Call build api to find existing payloads.

    # Schedule Children payloads for non-existent payloads.

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
      'discovering configuration.get paygen json.gsutil cat',
      api.cros_paygen.EXAMPLE_PAYGEN_JSON)

  yield api.test('basic', get_props(), good_paygen,
                 api.post_check(post_process.StatusSuccess))
  yield api.test('no-payloads', get_props(builder_name='goobolywhobbly'),
                 good_paygen, api.post_check(post_process.StatusSuccess))
