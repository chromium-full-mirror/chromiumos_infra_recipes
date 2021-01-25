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
    api.cros_source.ensure_synced_cache(
        projects=[api.cros_release_config.LEGACY_CONFIG_PROJECT])
    # TODO(b/177903295): Release branch name should come from branch_create recipe output.
    api.cros_release_config.update_config('release-foo.B')


def GenTests(api):
  yield api.test('basic')
