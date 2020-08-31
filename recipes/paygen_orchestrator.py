# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for orchestrating ChromeOS payloads (AU deltas etc)."""

DEPS = [
    'recipe_engine/step',
    'cros_paygen',
    'cros_sdk',
    'cros_source',
    'workspace_util',
]


def RunSteps(api):
  with api.workspace_util.setup_workspace(), \
                  api.cros_sdk.cleanup_context():

    # Get the current paygen configuration.

    # TODO(engeg@): Integrate test data or move most logic to module.
    # paygen_config = api.cros_paygen.get_builder_config(builder_name='arkham')

    # Sync chromite only.
    api.cros_source.ensure_synced_cache(projects=['chromiumos/chromite'])

    # Call module to look for existing payloads?

    # Schedule Children payloads for non-existent payloads.

    # Collect and handle failures.

    # Schedule AU tests if configured, don't wait for them.

def GenTests(api):
  yield api.test('basic')
