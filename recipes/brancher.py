# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for creating a new ChromeOS branch."""

DEPS = [
    'cros_release_config',
    'cros_sdk',
    'cros_source',
    'workspace_util',
]


def RunSteps(api):
  # TODO(b/177903295): This is a stub.

  with api.workspace_util.setup_workspace(), api.cros_sdk.cleanup_context():
    api.cros_source.ensure_synced_cache(projects=[
        api.cros_release_config.LEGACY_CONFIG_PROJECT,
        api.cros_release_config.CONFIG_PROJECT
    ])
    # TODO: Release branch name should come from branch_create recipe output.
    api.cros_release_config.update_config('release-R01-00001.B')


def GenTests(api):
  yield api.test('basic')
