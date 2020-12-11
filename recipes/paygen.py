# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for generating ChromeOS payloads (AU deltas etc)."""

import json

DEPS = [
    'recipe_engine/step',
    'cros_build_api',
    'cros_sdk',
    'cros_source',
    'workspace_util',
]

from PB.recipes.chromeos.paygen import PaygenProperties

PROPERTIES = PaygenProperties


def RunSteps(api, properties):
  with api.workspace_util.setup_workspace(), api.cros_sdk.cleanup_context():
    with api.step.nest('initialization'):

      # Sync chromite only.
      api.cros_source.ensure_synced_cache(projects=['chromiumos/chromite'])

      # Create chroot.
      api.cros_sdk.create_chroot(version=None, use_image=False,
                                 timeout_sec=None)

    with api.step.nest('doing paygen'):
      # Execute build api endpoint for paygen.
      response = api.cros_build_api.PayloadService.GeneratePayload(
          properties.request, name='making single payload')


def GenTests(api):

  def generate_payload_response(api, is_success=True, local_path='',
                                remote_uri=''):
    data = json.dumps(
        dict(success=is_success, local_path=local_path, remote_uri=remote_uri))
    return api.cros_build_api.set_api_return(parent_step_name='doing paygen',
                                             step_name='making single payload',
                                             data=data,
                                             retcode=0 if is_success else 1)

  yield api.test('basic')

  yield api.test('dryrun', generate_payload_response(api))
